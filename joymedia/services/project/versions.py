"""Explicit project families, editable branches and immutable export history.

Grouping never rewrites generation lineage, moves files, or infers identity from a
product name. A working edit is a navigation preference, not a release approval.
"""

import json

import frappe
from frappe import _


def family(project):
	root = frappe.get_doc("Media Project", project.version_of) if project.get("version_of") else project
	root._require_read_access()
	if root.get("version_of") or root.owner != project.owner:
		frappe.throw(_("Invalid project version ownership."), frappe.PermissionError)
	return root


def validate_membership(project):
	"""Protect direct document writes as well as the public organization endpoints."""
	if project.get("version_of"):
		if project.version_of == project.name:
			frappe.throw(_("A project cannot be its own parent."))
		root = frappe.get_doc("Media Project", project.version_of)
		root._require_write_access()
		if root.get("version_of") or root.owner != project.owner:
			frappe.throw(_("Edit versions must belong to a root project with the same owner."))
		if not project.is_new() and frappe.db.exists("Media Project", {"version_of": project.name}):
			frappe.throw(_("A project with edit versions cannot become another edit."))
		if project.get("current_edit"):
			frappe.throw(_("Only the parent project has a working edit."))
	if project.get("current_edit") and project.current_edit != project.name:
		child = frappe.db.get_value(
			"Media Project", project.current_edit, ["version_of", "owner", "status"], as_dict=True
		)
		if (
			not child
			or child.version_of != project.name
			or child.owner != project.owner
			or child.status == "Archived"
		):
			frappe.throw(_("The working edit must be an active version of this project."))


def members(root):
	return [
		root.name,
		*frappe.get_all(
			"Media Project", filters={"version_of": root.name, "owner": root.owner}, pluck="name"
		),
	]


def summary(project):
	root = family(project)
	current = root.get("current_edit") or root.name
	return {
		"root": root.name,
		"project_name": root.project_name,
		"current_edit": current,
		"edit": project.name,
		"edit_label": project.get("version_label")
		or ("Original" if project.name == root.name else project.project_name),
		"edit_kind": project.get("version_kind") or "Creative",
		"is_working_edit": current == project.name,
		"archived": root.status == "Archived" or project.status == "Archived",
	}


def assert_idle(names):
	if frappe.db.exists(
		"Generation Run", {"media_project": ["in", names], "status": ["in", ["Draft", "Queued", "Running"]]}
	):
		frappe.throw(_("Wait for active generations to finish before reorganizing these edits."))
	for field in ("export_status", "post_production_status", "planning_status"):
		if frappe.db.exists(
			"Media Project", {"name": ["in", names], field: ["in", ["Queued", "Running", "Planning"]]}
		):
			frappe.throw(_("Wait for editing jobs to finish before reorganizing these edits."))


def _label(value):
	value = " ".join(str(value or "").split())
	if not value or len(value) > 100:
		frappe.throw(_("Enter an edit name of 1 to 100 characters."))
	return value


@frappe.whitelist(methods=["POST"])
def organize_edits(project_name, edits):
	"""Explicit, atomic grouping; suitable for repairing legacy duplicate projects."""
	root = frappe.get_doc("Media Project", project_name)
	root._require_write_access()
	if root.get("version_of"):
		frappe.throw(_("Choose the parent project."))
	edits = frappe.parse_json(edits) if isinstance(edits, str) else edits
	if not isinstance(edits, list) or not edits or len(edits) > 100:
		frappe.throw(_("Choose between 1 and 100 edits."))
	with frappe.cache.lock(
		f"joymedia-project-versions:{frappe.local.site}:{root.name}", timeout=120, blocking_timeout=10
	):
		frappe.db.sql("select name from `tabMedia Project` where name=%s for update", root.name)
		names, changes = set(), []
		for row in edits:
			if (
				not isinstance(row, dict)
				or not isinstance(row.get("project"), str)
				or row["project"] in names
				or row["project"] == root.name
			):
				frappe.throw(_("Each edit must be a distinct project."))
			names.add(row["project"])
			doc = frappe.get_doc("Media Project", row["project"])
			doc._require_write_access(allow_archived=True)
			if (
				doc.owner != root.owner
				or doc.get("version_of") not in (None, "", root.name)
				or frappe.db.exists("Media Project", {"version_of": doc.name})
			):
				frappe.throw(_("These edits cannot be grouped without changing another project family."))
			kind = row.get("kind", "Creative")
			if kind not in ("Creative", "Experiment"):
				frappe.throw(_("Invalid edit type."))
			changes.append((doc, _label(row.get("label")), kind))
		assert_idle([root.name, *names])
		for doc, label, kind in changes:
			# Organization metadata must not revalidate or rewrite a legacy creative brief.
			doc.db_set(
				{"version_of": root.name, "version_label": label, "version_kind": kind, "current_edit": None},
				update_modified=False,
			)
	return {"project": root.name, "edits": len(changes)}


@frappe.whitelist(methods=["POST"])
def set_working_edit(project_name, edit_name, expected_current):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	root = family(project)
	root._require_write_access()
	frappe.db.sql("select name from `tabMedia Project` where name=%s for update", root.name)
	root.reload()
	if (root.get("current_edit") or root.name) != expected_current:
		frappe.throw(_("The working edit changed in another tab. Refresh history and try again."))
	target = frappe.get_doc("Media Project", edit_name)
	target._require_read_access()
	if root.status == "Archived" or target.status == "Archived" or family(target).name != root.name:
		frappe.throw(_("Choose an active edit in this project."))
	root.db_set("current_edit", target.name, update_modified=False)
	return {"project": root.name, "current_edit": target.name}


@frappe.whitelist(methods=["POST"])
def rename_edit(project_name, label):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	project.db_set("version_label", _label(label))
	return summary(project)


@frappe.whitelist()
def get_history(project_name, kind="edits", start=0, page_length=30, shot_name=None):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	root = family(project)
	try:
		start, page_length = max(0, int(start)), min(100, max(1, int(page_length)))
	except ValueError, TypeError:
		frappe.throw(_("Invalid history paging."))
	names = members(root)
	if shot_name and not frappe.db.exists("Shot", {"name": shot_name, "media_project": ["in", names]}):
		frappe.throw(_("Choose a scene in this project."))
	scenes = []
	if kind == "takes":
		scenes = frappe.db.sql(
			"""select s.name, s.shot_number, s.shot_name, s.media_project,
			coalesce(nullif(p.version_label, ''), p.project_name) as edit_label
			from `tabShot` s join `tabMedia Project` p on p.name=s.media_project
			where s.media_project in %(names)s
			order by p.creation desc, s.shot_number, s.name""",
			{"names": names},
			as_dict=True,
		)
	if kind == "edits":
		rows = frappe.get_all(
			"Media Project",
			filters={"name": ["in", names]},
			fields=[
				"name",
				"project_name",
				"version_label",
				"version_kind",
				"status",
				"creation",
				"modified",
				"current_output_asset_version",
			],
			order_by="creation desc",
			limit_page_length=0,
		)
		# Keep the working cut visible before diagnostics, even after many experiments.
		rows.sort(key=lambda row: (str(row.creation), row.name), reverse=True)
		rows.sort(
			key=lambda row: (
				row.name != (root.get("current_edit") or root.name),
				row.status == "Archived",
				row.version_kind == "Experiment",
			)
		)
		rows = rows[start : start + page_length + 1]
		for row in rows:
			row["label"] = row.version_label or ("Original" if row.name == root.name else row.project_name)
			row["is_working_edit"] = row.name == (root.get("current_edit") or root.name)
			row["has_export"] = bool(row.current_output_asset_version)
	elif kind == "activity":
		rows = frappe.get_all(
			"Generation Run",
			filters={"media_project": ["in", names]},
			fields=[
				"name",
				"media_project",
				"status",
				"creation",
				"total_tasks",
				"completed_tasks",
				"failed_tasks",
			],
			order_by="creation desc",
			limit_start=start,
			limit_page_length=page_length + 1,
		)
		labels = {
			row.name: row.version_label or row.project_name
			for row in frappe.get_all(
				"Media Project",
				filters={"name": ["in", names]},
				fields=["name", "version_label", "project_name"],
			)
		}
		for row in rows:
			row["version_label"] = labels.get(row.media_project)
	elif kind in ("exports", "takes"):
		# Exact logical asset names are the established application output contract.
		condition = (
			"a.asset_name = concat(a.media_project, %s)" if kind == "exports" else "a.asset_name like %s"
		)
		pattern = " Final Video" if kind == "exports" else "SHOT-% Output"
		rows = frappe.db.sql(
			f"""select v.name, v.version_number, v.file, v.creation, v.duration_seconds,
			v.width, v.height, v.source_generation_attempt, v.derived_from, v.content_hash, v.source,
			s.name as shot, s.shot_number, s.shot_name, s.selected_output_asset_version as selected_version, case when s.selected_output_asset_version=v.name then 1 else 0 end as is_selected,
			a.media_project, a.asset_name, coalesce(nullif(p.version_label, ''), p.project_name) as version_label,
			case when coalesce(v.release_evidence_json, '') != '' then 'release' else 'review' end as purpose,
			case when coalesce(v.edit_manifest_json, '') != '' then 1 else 0 end as has_edit_snapshot
			from `tabAsset Version` v join `tabMedia Asset` a on a.name=v.media_asset
			join `tabMedia Project` p on p.name=a.media_project
			left join `tabShot` s on s.media_project=a.media_project and a.asset_name=concat(s.name, ' Output')
			where a.media_project in %(names)s and a.asset_scope='Project Output' and a.media_type='Video'
			and {condition.replace("%s", "%(pattern)s")}
			{"and s.name = %(shot)s" if shot_name and kind == "takes" else ""}
			order by v.creation desc, v.name desc limit %(limit)s offset %(start)s""",
			{"names": names, "pattern": pattern, "limit": page_length + 1, "start": start, "shot": shot_name},
			as_dict=True,
		)
	else:
		frappe.throw(_("Choose edit, export or scene take history."))
	return {
		"family": summary(project),
		"can_select_takes": bool(
			project.status != "Archived"
			and root.status != "Archived"
			and frappe.has_permission("Media Project", "write", doc=project)
		),
		"kind": kind,
		"items": rows[:page_length],
		"scenes": scenes,
		"has_more": len(rows) > page_length,
		"start": start,
	}


@frappe.whitelist(methods=["POST"])
def create_edit(project_name, label, kind="Creative", expected_current=None, make_working=True):
	"""Copy mutable edit state, share media bytes, retain baseline lineage; no GPU work."""
	source = frappe.get_doc("Media Project", project_name)
	source._require_write_access()
	root = family(source)
	root._require_write_access()
	if kind not in ("Creative", "Experiment"):
		frappe.throw(_("Invalid edit type."))
	label = _label(label)
	with frappe.cache.lock(
		f"joymedia-take-admission:{frappe.local.site}:{source.name}", timeout=120, blocking_timeout=10
	):
		frappe.db.sql("select name from `tabMedia Project` where name=%s for update", root.name)
		root.reload()
		source.reload()
		if root.status == "Archived" or source.status == "Archived":
			frappe.throw(_("Restore the project before creating an edit."))
		if expected_current is not None and (root.get("current_edit") or root.name) != expected_current:
			frappe.throw(_("The working edit changed. Refresh history first."))
		assert_idle([source.name])
		copy = frappe.copy_doc(source)
		copy.version_of, copy.version_label, copy.version_kind, copy.current_edit = (
			root.name,
			label,
			kind,
			None,
		)
		copy.project_name = root.project_name
		for field in (
			"current_output_asset_version",
			"approved_plan_signature",
			"export_error",
			"export_started_at",
			"export_completed_at",
			"post_production_step",
			"post_production_error",
			"post_production_comfy_prompt_id",
			"post_production_requested_at",
			"planning_error",
		):
			copy.set(field, None)
		copy.storyboard_approval_status = "Draft"
		copy.export_status = copy.post_production_status = copy.planning_status = "Idle"
		copy.insert(ignore_permissions=True)
		shot_map, take_map, timings, reference_map = {}, {}, [], {}
		for reference in copy.selected_media or []:
			reference.asset_version = copy_control_reference(
				reference.asset_version, source, copy, reference_map
			)
		copy.save(ignore_permissions=True)
		for name in frappe.get_all(
			"Shot",
			filters={"media_project": source.name, "is_removed": 0},
			pluck="name",
			order_by="shot_number",
		):
			old = frappe.get_doc("Shot", name)
			shot = frappe.copy_doc(old)
			shot.media_project = copy.name
			for reference in shot.generation_inputs or []:
				reference.asset_version = copy_control_reference(
					reference.asset_version, source, copy, reference_map
				)
			plan = frappe.parse_json(shot.motion_plan_json or "{}") or {}
			for placement in plan.get("artwork_placements", []):
				placement["asset_version"] = copy_control_reference(
					placement["asset_version"], source, copy, reference_map
				)
			if plan.get("artwork_placements"):
				shot.motion_plan_json = frappe.as_json(plan)
			for field in (
				"selected_output_asset_version",
				"brand_approval_signature",
				"brand_approved_by",
				"brand_approved_at",
				"consistency_notes",
			):
				shot.set(field, None)
			shot.consistency_status, shot.consistency_retries = "Not Checked", 0
			shot.insert(ignore_permissions=True)
			shot_map[old.name] = shot.name
			timings.append(
				(shot.name, {field: old.get(field) for field in ("duration_seconds", "planned_frame_count")})
			)
			if old.selected_output_asset_version:
				baseline = frappe.get_doc("Asset Version", old.selected_output_asset_version)
				asset = frappe.copy_doc(frappe.get_doc("Media Asset", baseline.media_asset))
				asset.media_project, asset.asset_name = copy.name, f"{shot.name} Output"
				asset.insert(ignore_permissions=True)
				version = frappe.copy_doc(baseline)
				version.media_asset = asset.name
				version.source, version.derived_from = "Derived", baseline.name
				version.release_evidence_json = version.edit_manifest_json = None
				version.insert(ignore_permissions=True)
				shot.db_set("selected_output_asset_version", version.name, update_modified=False)
				take_map[(old.name, baseline.name)] = version.name
		# Sequential Shot insertion redistributes unscripted timing; restore the source split.
		for name, values in timings:
			frappe.db.set_value("Shot", name, values, update_modified=False)
		clip_map, restores = {}, []
		for name in frappe.get_all(
			"Timeline Clip", filters={"media_project": source.name}, pluck="name", order_by="creation"
		):
			old = frappe.get_doc("Timeline Clip", name)
			clip = frappe.copy_doc(old)
			clip.media_project, clip.shot = copy.name, shot_map.get(old.shot)
			clip.linked_video_clip = None
			clip.insert(ignore_permissions=True)
			clip_map[old.name] = clip.name
			restores.append((clip.name, old.as_dict()))
		# Insertion hooks normalize timelines. Restore the exact source EDL after all neighbors exist.
		clip_fields = {
			row.fieldname
			for row in frappe.get_meta("Timeline Clip").fields
			if row.fieldtype not in ("Section Break", "Column Break", "Tab Break")
		}
		for name, old in restores:
			linked = old.get("linked_video_clip")
			if linked and linked not in clip_map:
				frappe.throw(_("Cannot copy an edit with a missing linked source clip."))
			values = {key: value for key, value in old.items() if key in clip_fields}
			values.update(
				media_project=copy.name,
				shot=shot_map.get(old.get("shot")),
				linked_video_clip=clip_map.get(linked),
				source_asset_version=take_map.get(
					(old.get("shot"), old.get("source_asset_version")), old.get("source_asset_version")
				),
			)
			frappe.db.set_value("Timeline Clip", name, values, update_modified=False)
		if clip_map:
			# A branch inherits an authored cut, not an empty timeline to rebuild.
			# Keep the source's baseline (whose clip IDs differ from the copy) so
			# finishing patches new takes without erasing trims, mutes or soundtrack.
			from joymedia.services.editing.post_production import timeline_signature

			copy.db_set(
				"finished_timeline_signature",
				source.finished_timeline_signature or timeline_signature(source.name),
				update_modified=False,
			)
		if str(make_working).lower() in {"true", "1", "yes", "on"}:
			root.db_set("current_edit", copy.name, update_modified=False)
	return {"project": root.name, "edit": copy.name, "label": label}


def export_manifest(project, clips, timeline_signature):
	"""Record render inputs without requiring a generation model to be installed."""
	fields = (
		"project_name",
		"product_name",
		"video_idea",
		"storyboard_source_json",
		"delivery_preset",
		"delivery_width",
		"delivery_height",
		"show_captions",
		"export_quality",
		"global_instructions",
		"soundtrack_mode",
		"selected_media",
	)
	state = {field: project.get(field) for field in fields}
	return json.dumps(
		{
			"version": 1,
			"project": project.name,
			"timeline_signature": timeline_signature,
			"project_state": state,
			"clips": [dict(row) for row in clips],
			"selected_takes": frappe.get_all(
				"Shot",
				filters={"media_project": project.name, "is_removed": 0},
				fields=[
					"name",
					"selected_output_asset_version",
					"shot_name",
					"shot_number",
					"image_prompt",
					"generation_prompt",
					"storyboard_action",
					"motion_plan_json",
				],
			),
		},
		default=lambda value: value.as_dict() if hasattr(value, "as_dict") else str(value),
		ensure_ascii=False,
	)


def card_rows(search=None, status=None, start=0, page_length=24):
	"""One root per card; pagination/counts use the chosen edit's actual status."""
	try:
		start, page_length = max(0, int(start)), min(100, max(1, int(page_length)))
	except ValueError, TypeError:
		frappe.throw(_("Invalid project paging."))
	filters = {}
	if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
		filters["owner"] = frappe.session.user
	rows = frappe.get_list(
		"Media Project",
		filters=filters,
		fields=[
			"name",
			"owner",
			"project_name",
			"product_name",
			"video_idea",
			"status",
			"modified",
			"version_of",
			"version_label",
			"version_kind",
			"current_edit",
			"current_output_asset_version",
		],
		limit_page_length=0,
	)
	by_name, children = {row.name: row for row in rows}, {}
	for row in rows:
		if row.version_of:
			children.setdefault(row.version_of, []).append(row)
	cards = []
	term = str(search or "").strip().casefold()
	for root in rows:
		if root.version_of:
			continue
		edits = [root, *[row for row in children.get(root.name, []) if row.owner == root.owner]]
		if term and not any(
			term in str(row.get(key) or "").casefold()
			for row in edits
			for key in ("project_name", "product_name", "video_idea", "version_label")
		):
			continue
		current = by_name.get(root.current_edit) or root
		if current not in edits or current.status == "Archived":
			current = root
		archived = root.status == "Archived"
		if archived != (status == "Archived"):
			continue
		cards.append(
			{
				**dict(root),
				"status": "Archived" if archived else current.status,
				"open_project": current.name,
				"edit_count": len(edits),
				"experiment_count": sum(row.version_kind == "Experiment" for row in edits),
				"current_output_asset_version": current.current_output_asset_version,
				"modified": max(row.modified for row in edits),
				"has_video": bool(current.current_output_asset_version),
			}
		)
	counts = {
		key: sum(row["status"] == key for row in cards)
		for key in ("Draft", "Generating", "Needs Attention", "Completed", "Cancelled", "Archived")
	}
	matching = [row for row in cards if not status or status == "All" or row["status"] == status]
	matching.sort(key=lambda row: (str(row["modified"]), row["name"]), reverse=True)
	return {
		"items": matching[start : start + page_length],
		"total": len(matching),
		"counts_by_status": counts,
	}


def exported_edit_is_outdated(project, manifest):
	"""None for legacy exports; otherwise compare to the exact exported inputs."""
	try:
		manifest = json.loads(manifest) if isinstance(manifest, str) else manifest
		if (
			not isinstance(manifest, dict)
			or not manifest.get("timeline_signature")
			or not isinstance(manifest.get("project_state"), dict)
		):
			return None
		from joymedia.services.editing.post_production import timeline_signature

		if manifest["timeline_signature"] != timeline_signature(project.name):
			return True

		def normalize(value):
			return json.loads(
				json.dumps(value, default=lambda v: v.as_dict() if hasattr(v, "as_dict") else str(v))
			)

		if any(normalize(project.get(key)) != value for key, value in manifest["project_state"].items()):
			return True
		for saved in manifest.get("selected_takes", []):
			current = frappe.db.get_value(
				"Shot",
				saved["name"],
				[
					"selected_output_asset_version",
					"image_prompt",
					"generation_prompt",
					"storyboard_action",
					"motion_plan_json",
				],
				as_dict=True,
			)
			if not current or any(current.get(key) != saved.get(key) for key in current):
				return True
		return False
	except (ValueError, TypeError, KeyError):
		return None


def copy_control_reference(version, source, target, copied):
	"""Copy edit-owned control metadata, sharing immutable bytes and lineage.

	Library versions stay selected references. Never grant a family-wide media
	access exception: each new edit owns its control versions and patch records.
	"""
	if not version:
		return version
	if version in copied:
		if copied[version] is None:
			frappe.throw(_("Control reference evidence contains a cycle."))
		return copied[version]
	original = frappe.get_doc("Asset Version", version)
	parent = frappe.get_doc("Media Asset", original.media_asset)
	if not parent.media_project:
		return version
	if parent.media_project == target.name:
		return version
	owner_project = frappe.get_doc("Media Project", parent.media_project)
	owner_project._require_read_access()
	if family(owner_project).name != family(source).name:
		frappe.throw(_("Control references must belong to this project family."), frappe.PermissionError)
	# Validate file integrity before sharing its URL into another edit.
	from joymedia.services.consistency.tracking import file_hash

	path = frappe.get_doc("File", {"file_url": original.file}).get_full_path()
	if file_hash(path) != original.content_hash:
		frappe.throw(_("Control reference bytes changed."))
	copied[version] = None
	media = frappe.copy_doc(parent)
	media.media_project = target.name
	media.insert(ignore_permissions=True)
	clone = frappe.copy_doc(original)
	clone.media_asset, clone.source, clone.derived_from = media.name, "Derived", original.name
	clone.release_evidence_json = None
	evidence = frappe.parse_json(original.preservation_evidence_json or "{}") or {}
	for item in (evidence.get("product_lock") or {}).get("items", []):
		if item.get("source_asset_version"):
			item["source_asset_version"] = copy_control_reference(
				item["source_asset_version"], source, target, copied
			)
		if item.get("patch_asset_version"):
			item["patch_asset_version"] = copy_control_reference(
				item["patch_asset_version"], source, target, copied
			)
	clone.preservation_evidence_json = frappe.as_json(evidence) if evidence else None
	clone.insert(ignore_permissions=True)
	copied[version] = clone.name
	return clone.name
