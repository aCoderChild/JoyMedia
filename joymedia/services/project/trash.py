"""Archived projects behave like a trash: restorable for 30 days, then deleted for good."""

import json

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, now_datetime

RETENTION_DAYS = 30


def days_left(archived_on):
	if not archived_on:
		return RETENTION_DAYS
	return max(0, RETENTION_DAYS - date_diff(now_datetime(), archived_on))


def delete_forever(project):
	"""Delete an archived video, or a whole archived project with all its videos."""
	from joymedia.services.project.versions import assert_idle, family, members

	if project.status != "Archived":
		frappe.throw(_("Move the video to the trash before deleting it for good."))
	root = family(project)
	names = members(root) if root.name == project.name else [project.name]
	assert_idle(names)
	_purge(names)
	return names


def purge_expired_trash():
	"""Daily: delete what has been in the trash longer than the retention period."""
	cutoff = add_days(now_datetime(), -RETENTION_DAYS)
	expired = frappe.get_all(
		"Media Project",
		filters={"status": "Archived", "archived_on": ["<", cutoff]},
		fields=["name", "version_of"],
	)
	expired_names = {row.name for row in expired}
	for row in expired:
		# A video inside an expired project goes with that project.
		if row.version_of in expired_names:
			continue
		try:
			from joymedia.services.project.versions import members

			root = frappe.get_doc("Media Project", row.name)
			names = members(root) if not row.version_of else [row.name]
			if frappe.db.exists(
				"Generation Run",
				{"media_project": ["in", names], "status": ["in", ["Draft", "Queued", "Running"]]},
			):
				continue
			_purge(names)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Trash purge failed for {row.name}")


def _names(doctype, filters):
	return set(frappe.get_all(doctype, filters=filters, pluck="name")) if filters else set()


def _purge(projects):
	projects = set(projects)
	shots = _names("Shot", {"media_project": ["in", list(projects)]})
	runs = _names("Generation Run", {"media_project": ["in", list(projects)]})
	tasks = _names("Generation Task", {"generation_run": ["in", list(runs)]}) if runs else set()
	if shots:
		tasks |= _names("Generation Task", {"shot": ["in", list(shots)]})
	attempts = _names("Generation Attempt", {"generation_task": ["in", list(tasks)]}) if tasks else set()
	artifacts = (
		_names("Generation Artifact", {"generation_attempt": ["in", list(attempts)]}) if attempts else set()
	)
	# Library items have no project; only what this project made or was given for itself goes.
	assets = _names("Media Asset", {"media_project": ["in", list(projects)]})
	versions = _names("Asset Version", {"media_asset": ["in", list(assets)]}) if assets else set()
	if attempts:
		versions |= _names("Asset Version", {"source_generation_attempt": ["in", list(attempts)]})
	doomed = {
		"Media Project": projects,
		"Shot": shots,
		"Generation Task": tasks,
		"Asset Version": versions,
	}
	kept = {v for v in versions if _used_elsewhere(v, doomed)}
	versions -= kept
	kept_assets = {frappe.db.get_value("Asset Version", v, "media_asset") for v in kept}
	for asset in kept_assets & assets:
		# Still used by a video that stays, so it outlives this project.
		frappe.db.set_value("Media Asset", asset, "media_project", None, update_modified=False)
	assets -= kept_assets
	files = (
		{
			url
			for url in frappe.get_all("Asset Version", filters={"name": ["in", list(versions)]}, pluck="file")
			+ frappe.get_all(
				"Generation Artifact", filters={"name": ["in", list(artifacts)]}, pluck="frappe_file"
			)
			if url
		}
		if versions or artifacts
		else set()
	)

	_detach_batches(projects)
	for doctype, filters in (
		("Review Comment", {"media_project": ["in", list(projects)]}),
		("Video Review Feedback", {"media_project": ["in", list(projects)]}),
		("Video Review Feedback", {"source_edit": ["in", list(projects)]}),
		("Timeline Clip", {"media_project": ["in", list(projects)]}),
	):
		for name in _names(doctype, filters):
			_delete(doctype, name)
	# Clear links between doomed records first so deletion order does not matter.
	for doctype, field, names in (
		("Generation Attempt", "retry_of", attempts),
		("Generation Task", "depends_on_task", tasks),
		("Asset Version", "derived_from", versions),
		("Shot", "selected_output_asset_version", shots),
		("Shot", "keyframe_artifact", shots),
		("Media Project", "current_output_asset_version", projects),
		("Media Project", "current_edit", projects),
	):
		for name in names:
			frappe.db.set_value(doctype, name, field, None, update_modified=False)
	for doctype, names in (
		("Generation Artifact", artifacts),
		("Generation Attempt", attempts),
		("Generation Task", tasks),
		("Generation Run", runs),
		("Asset Version", versions),
		("Media Asset", assets),
		("Shot", shots),
	):
		for name in names:
			_delete(doctype, name)
	# Videos before their parent project.
	for name in sorted(
		projects, key=lambda n: bool(frappe.db.get_value("Media Project", n, "version_of")), reverse=True
	):
		_delete("Media Project", name)
	for url in files:
		if frappe.db.exists("Asset Version", {"file": url}) or frappe.db.exists(
			"Generation Artifact", {"frappe_file": url}
		):
			continue
		for file_name in frappe.get_all("File", filters={"file_url": url}, pluck="name"):
			_delete("File", file_name)


def _used_elsewhere(version, doomed):
	"""True when a record that is not being deleted still points at this version."""
	if frappe.db.exists("Partner Video", {"asset_version": version}):
		return True
	for doctype, field, owner, owner_doctype in (
		("Project Reference", "asset_version", "parent", "Media Project"),
		("Shot Reference", "asset_version", "parent", "Shot"),
		("Generation Input", "asset_version", "parent", "Generation Task"),
		("Shot", "selected_output_asset_version", "name", "Shot"),
		("Media Project", "current_output_asset_version", "name", "Media Project"),
		("Asset Version", "derived_from", "name", "Asset Version"),
		("Timeline Clip", "source_asset_version", "media_project", "Media Project"),
		("Review Comment", "output_asset_version", "media_project", "Media Project"),
		("Video Review Feedback", "asset_version", "media_project", "Media Project"),
	):
		owners = set(frappe.get_all(doctype, filters={field: version}, pluck=owner))
		if owners - doomed.get(owner_doctype, set()):
			return True
	return False


def _detach_batches(projects):
	"""Batches started from a deleted project go; others forget the deleted videos."""
	for name in frappe.get_all("Creative Batch", pluck="name"):
		with frappe.cache.lock(f"joymedia-creative:{name}", timeout=180, blocking_timeout=30):
			batch = frappe.db.get_value(
				"Creative Batch", name, ["source_project", "variants_json"], as_dict=True
			)
			if batch.source_project in projects:
				_delete("Creative Batch", name)
				continue
			variants = json.loads(batch.variants_json or "[]")
			if not any(v.get("project") in projects for v in variants):
				continue
			for variant in variants:
				if variant.get("project") in projects:
					variant.update(project=None, status="Cancelled")
			frappe.db.set_value(
				"Creative Batch",
				name,
				"variants_json",
				json.dumps(variants, ensure_ascii=False),
				update_modified=False,
			)


def _delete(doctype, name):
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(
			doctype, name, force=True, ignore_permissions=True, delete_permanently=True, ignore_on_trash=True
		)
