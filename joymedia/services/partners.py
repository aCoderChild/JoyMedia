"""Explicit partner publication and sandbox policy. Reviewer grants never expose a project's working data."""

import frappe
from frappe import _
from werkzeug.utils import send_file

ROLE = "JoyMedia Reviewer"


def is_reviewer(user=None):
	user = user or frappe.session.user
	return (
		user != "Administrator"
		and "System Manager" not in frappe.get_roles(user)
		and ROLE in frappe.get_roles(user)
	)


def policy(user=None, required=True):
	user = user or frappe.session.user
	row = frappe.db.get_value(
		"Partner Access",
		{"user": user},
		[
			"name",
			"enabled",
			"allow_generation",
			"allow_feedback",
			"allow_download",
			"max_projects",
			"max_model_jobs",
			"model_jobs_used",
			"max_duration_seconds",
			"max_pixels",
		],
		as_dict=True,
	)
	if not row or not row.enabled or not frappe.db.get_value("User", user, "enabled"):
		if required:
			frappe.throw(
				_("Partner access is not enabled. Contact your administrator."), frappe.PermissionError
			)
		return None
	return row


def published_target(asset_version):
	version = frappe.get_doc("Asset Version", asset_version)
	asset = frappe.get_doc("Media Asset", version.media_asset)
	if asset.media_type != "Video" or asset.asset_scope != "Project Output" or not asset.media_project:
		frappe.throw(_("Publish a completed project video or scene version."))
	shot = frappe.db.get_value(
		"Shot",
		{"media_project": asset.media_project, "name": asset.asset_name.removesuffix(" Output")},
		"name",
	)
	if asset.asset_name != f"{asset.media_project} Final Video" and (
		not shot or asset.asset_name != f"{shot} Output"
	):
		frappe.throw(_("Publish a full-video or scene output."))
	return asset, version


def require_published(asset_version, feedback=False, download=False):
	p = policy()
	if not frappe.db.exists(
		"Partner Video", {"parent": p.name, "parenttype": "Partner Access", "asset_version": asset_version}
	):
		frappe.throw(_("This video has not been shared with your account."), frappe.PermissionError)
	if feedback and not p.allow_feedback:
		frappe.throw(_("Feedback is disabled for this account."), frappe.PermissionError)
	if download and not p.allow_download:
		frappe.throw(_("Downloads are disabled for this account."), frappe.PermissionError)
	return p


def require_generation(project=None):
	p = policy()
	if not p.allow_generation or (project is not None and project.owner != frappe.session.user):
		frappe.throw(
			_("Your reviewer account cannot modify or generate this project."), frappe.PermissionError
		)
	return p


def validate_project(doc):
	owner = doc.owner or frappe.session.user
	if not is_reviewer(owner):
		return
	p = policy(owner)
	if not p.allow_generation:
		frappe.throw(_("Test generation is disabled for this partner."), frappe.PermissionError)
	if doc.is_new():
		locked = frappe.db.sql(
			"select enabled, allow_generation, max_projects, max_duration_seconds, max_pixels from `tabPartner Access` where name=%s for update",
			p.name,
			as_dict=True,
		)[0]
		p.update(locked)
		if not p.enabled or not p.allow_generation:
			frappe.throw(_("Partner generation access has been revoked."), frappe.PermissionError)
		count = frappe.db.sql("select count(*) from `tabMedia Project` where owner=%s for update", owner)[0][
			0
		]
		if count >= p.max_projects:
			frappe.throw(_("The partner test-project limit has been reached."))
	if (
		float(doc.total_duration_seconds or 0) > p.max_duration_seconds
		or int(doc.delivery_width or 0) * int(doc.delivery_height or 0) > p.max_pixels
	):
		frappe.throw(_("This video exceeds the partner duration or resolution limit."))
	before = doc.get_doc_before_save()
	if (
		before
		and is_reviewer()
		and any(
			doc.get(k) != before.get(k) for k in ("workflow", "generation_pipeline", "version_of", "owner")
		)
	):
		frappe.throw(
			_("Reviewer accounts cannot change pipeline or project ownership."), frappe.PermissionError
		)


def require_worker_generation(project):
	owner = getattr(project, "owner", None)
	if isinstance(owner, str) and is_reviewer(owner):
		access = policy(owner)
		if not access.allow_generation:
			frappe.throw(_("Partner generation access has been revoked."), frappe.PermissionError)


def charge_attempt(doc, method=None):
	run = frappe.db.get_value("Generation Task", doc.generation_task, "generation_run")
	project_name = frappe.db.get_value("Generation Run", run, "media_project") if run else None
	owner = frappe.db.get_value("Media Project", project_name, "owner") if project_name else None
	if not owner or not is_reviewer(owner):
		return
	p = policy(owner)
	if not p.allow_generation:
		frappe.throw(_("Partner generation access has been revoked."), frappe.PermissionError)
	frappe.db.sql("select name from `tabPartner Access` where name=%s for update", p.name)
	rows = frappe.db.sql(
		"select model_jobs_used, max_model_jobs, enabled, allow_generation from `tabPartner Access` where name=%s for update",
		p.name,
		as_dict=True,
	)
	current = rows[0]
	if (
		not current.enabled
		or not current.allow_generation
		or current.model_jobs_used >= current.max_model_jobs
	):
		frappe.throw(_("The partner model-job allowance has been reached or disabled."))
	frappe.db.sql("update `tabPartner Access` set model_jobs_used=model_jobs_used+1 where name=%s", p.name)


@frappe.whitelist()
def get_access(project_name=None):
	from joymedia.services.access import portal_access

	access = portal_access()
	if not access['reviewer']:
		return {**access, 'enabled': access['role'] != 'unassigned', 'can_open_project': access['role'] != 'unassigned'}
	p = policy(required=False)
	return {
		**access,
		"enabled": bool(p),
		"can_create": bool(p and p.allow_generation),
		"allow_generation": bool(p and p.allow_generation),
		"allow_download": bool(p and p.allow_download),
		"allow_feedback": bool(p and p.allow_feedback),
		"jobs_remaining": max(0, p.max_model_jobs - p.model_jobs_used) if p else 0,
		"can_open_project": bool(
			p
			and p.allow_generation
			and (
				not project_name
				or frappe.db.get_value("Media Project", project_name, "owner") == frappe.session.user
			)
		),
	}


@frappe.whitelist()
def get_review_library():
	if not is_reviewer():
		frappe.throw(_("This view is for partner reviewer accounts."), frappe.PermissionError)
	p = policy()
	items = []
	for row in frappe.get_all(
		"Partner Video",
		filters={"parent": p.name, "parenttype": "Partner Access"},
		fields=["asset_version", "label"],
		order_by="idx asc",
	):
		asset, version = published_target(row.asset_version)
		items.append(
			{
				"asset_version": version.name,
				"title": row.label,
				"project": asset.media_project,
				"duration_seconds": version.duration_seconds,
				"file": media_url(version.name),
				"download_url": media_url(version.name, download=True) if p.allow_download else None,
			}
		)
	return {
		"items": items,
		"allow_feedback": bool(p.allow_feedback),
		"allow_download": bool(p.allow_download),
		"allow_generation": bool(p.allow_generation),
	}


def media_url(version, download=False):
	from urllib.parse import urlencode

	return "/api/method/joymedia.services.partners.review_media?" + urlencode(
		{"asset_version": version, "download": int(download)}
	)


@frappe.whitelist()
def review_media(asset_version, download=0):
	download = str(download).lower() in ("1", "true")
	require_published(asset_version, download=download)
	_asset, version = published_target(asset_version)
	from joymedia.services.editing.composer import _get_asset_version_path

	path = _get_asset_version_path(version.name)
	response = send_file(
		str(path),
		environ=frappe.local.request.environ,
		conditional=True,
		as_attachment=download,
		download_name=f"{version.name}.mp4",
	)
	response.headers["Cache-Control"] = "private, no-store"
	return response


def document_permission(doc, user=None, permission_type=None, ptype=None, debug=False):
	user = user or frappe.session.user
	if not is_reviewer(user):
		return True
	p = policy(user, required=False)
	if not p or not p.allow_generation:
		return False
	kind = permission_type or ptype or "read"
	if kind not in ("read", "write", "create"):
		return False
	if doc.doctype == "Media Project":
		return doc.owner == user
	if doc.doctype == "Asset Version":
		if kind != "read":
			return False
		doc = frappe.get_doc("Media Asset", doc.media_asset)
	if doc.doctype == "Media Asset":
		return (
			frappe.db.get_value("Media Project", doc.media_project, "owner") == user
			if doc.media_project
			else doc.owner == user
		)
	return False


def project_query(user=None):
	return _query("Media Project", user)


def asset_query(user=None):
	return _query("Media Asset", user)


def version_query(user=None):
	return _query("Asset Version", user)


def _query(doctype, user):
	user = user or frappe.session.user
	if not is_reviewer(user):
		return ""
	p = policy(user, required=False)
	if not p or not p.allow_generation:
		return "1=0"
	escaped = frappe.db.escape(user)
	if doctype == "Media Project":
		return f"`tabMedia Project`.owner={escaped}"
	alias = "`tabMedia Asset`" if doctype == "Media Asset" else "a"
	condition = f"({alias}.media_project in (select name from `tabMedia Project` where owner={escaped}) or (coalesce({alias}.media_project,'')='' and {alias}.owner={escaped}))"
	if doctype == "Media Asset":
		return condition

	return f"`tabAsset Version`.media_asset in (select a.name from `tabMedia Asset` a where {condition})"
