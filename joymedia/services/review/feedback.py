"""Version-bound product feedback for administrator triage, independent of generation commands."""

import hashlib
import json
import math
import re

import frappe
from frappe import _
from frappe.utils import get_fullname

from joymedia.services.editing.view import _project_fps
from joymedia.services.project.context import _get_asset_version_file_url
from joymedia.services.project.versions import family, members

CATEGORIES = ("Other", "Brand", "Anatomy", "Physics", "Continuity", "Audio", "Text")
STATUSES = ("Open", "Investigating", "Resolved", "Dismissed")


def target(project_name, asset_version):
	project = frappe.get_doc("Media Project", project_name)
	from joymedia.services.partners import is_reviewer, policy, require_published

	partner = is_reviewer()
	shared = partner and (project.owner != frappe.session.user or not policy().allow_generation)
	if shared:
		require_published(asset_version)
		root = frappe.get_doc("Media Project", project.version_of) if project.get("version_of") else project
		if root.get("version_of") or root.owner != project.owner:
			frappe.throw(_("Invalid project version ownership."), frappe.PermissionError)
	else:
		project._require_read_access()
		root = family(project)
	version = frappe.get_doc("Asset Version", asset_version)
	asset = frappe.get_doc("Media Asset", version.media_asset)
	if (
		asset.media_project not in members(root)
		or asset.media_type != "Video"
		or asset.asset_scope != "Project Output"
	):
		frappe.throw(_("Choose a video version in this project."))
	shot = frappe.db.get_value(
		"Shot",
		{"media_project": asset.media_project, "name": asset.asset_name.removesuffix(" Output")},
		"name",
	)
	if asset.asset_name != f"{asset.media_project} Final Video" and (
		not shot or asset.asset_name != f"{shot} Output"
	):
		frappe.throw(_("Choose a full video or a scene version."))
	fps = float(version.fps or _project_fps(asset.media_project))
	duration = float(version.duration_seconds or 0)
	if not math.isfinite(fps) or fps <= 0 or not math.isfinite(duration) or duration <= 0:
		frappe.throw(_("This video needs valid timing metadata before it can be reviewed."))
	return root, asset, version, shot, fps, max(1, round(duration * fps))


def annotation(value):
	if value in (None, "", {}):
		return None
	try:
		if isinstance(value, str):
			value = json.loads(value)
		if not isinstance(value, dict):
			raise ValueError
		is_point = value.get("type") == "point"
		keys = {"x", "y"} if is_point else {"x", "y", "width", "height"}
		if set(value) != keys | ({"type"} if is_point else set()):
			raise ValueError
		if any(type(value[key]) not in (int, float) for key in keys):
			raise ValueError
		result = {key: float(value[key]) for key in keys}
		if not all(math.isfinite(v) and 0 <= v <= 1 for v in result.values()):
			raise ValueError
		if is_point:
			return {"type": "point", **result}
		if (
			result["width"] <= 0
			or result["height"] <= 0
			or result["x"] + result["width"] > 1.000001
			or result["y"] + result["height"] > 1.000001
		):
			raise ValueError
		return result
	except (TypeError, ValueError, OverflowError):
		frappe.throw(_("Mark an area inside the video frame."))


def _frame(value):
	try:
		result = float(value)
		if not math.isfinite(result) or result < 0 or result != int(result):
			raise ValueError
		return int(result)
	except (TypeError, ValueError, OverflowError):
		frappe.throw(_("Choose a valid video frame."))


@frappe.whitelist(methods=["POST"])
def add_feedback(
	project_name,
	asset_version,
	feedback,
	request_id,
	start_frame=None,
	end_frame=None,
	category="Other",
	priority="Normal",
	annotation_json=None,
):
	from joymedia.services.review.comments import _retrying

	# A waiting transaction may have read the old review index before another request committed.
	# Retry the entire admission with a fresh transaction, preserving the same idempotency key.
	return _retrying(
		lambda: _add_feedback(
			project_name,
			asset_version,
			feedback,
			request_id,
			start_frame,
			end_frame,
			category,
			priority,
			annotation_json,
		)
	)


def _add_feedback(
	project_name,
	asset_version,
	feedback,
	request_id,
	start_frame=None,
	end_frame=None,
	category="Other",
	priority="Normal",
	annotation_json=None,
):
	from joymedia.services.partners import is_reviewer, policy

	if is_reviewer():
		access = policy()
		if not access.allow_feedback:
			frappe.throw(_("Feedback is disabled for this account."), frappe.PermissionError)
	root, asset, version, shot, fps, limit = target(project_name, asset_version)
	if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", str(request_id)):
		frappe.throw(_("A valid submission ID is required."))
	start = _frame(start_frame) if start_frame not in (None, "") else None
	end = _frame(end_frame) if end_frame not in (None, "") else start
	if (start is None and end is not None) or (start is not None and (end < start or end >= limit)):
		frappe.throw(_("Choose a range inside this video."))
	box = annotation(annotation_json)
	if box and start is None:
		frappe.throw(_("A marked area must refer to a video frame."))
	key = hashlib.sha256(f"{frappe.session.user}:{version.name}:{request_id}".encode()).hexdigest()
	# Serialize retries and the per-reviewer limit on the immutable version, across web workers.
	frappe.db.sql("select name from `tabAsset Version` where name=%s for update", version.name)
	existing_rows = frappe.db.sql(
		"select * from `tabVideo Review Feedback` where submission_key=%s for update", key, as_dict=True
	)
	existing = existing_rows[0] if existing_rows else None
	payload = dict(
		media_project=root.name,
		source_edit=asset.media_project,
		asset_version=version.name,
		shot=shot,
		status="Open",
		fps=fps,
		start_frame=start,
		end_frame=end,
		scope="Video" if start is None else "Frame" if start == end else "Range",
		feedback=feedback,
		category=category,
		priority=priority,
		annotation_json=json.dumps(box) if box else None,
	)
	doc = frappe.get_doc({"doctype": "Video Review Feedback", **payload, "submission_key": key})
	doc.validate()
	if existing:
		previous = existing
		if any(
			previous.get(k) != doc.get(k)
			for k in (
				"feedback",
				"category",
				"priority",
				"scope",
				"start_frame",
				"end_frame",
				"annotation_json",
			)
		):
			frappe.throw(_("This submission ID was already used for different feedback."))
		return _row(previous)
	open_count = frappe.db.sql(
		"""select count(*) from `tabVideo Review Feedback`
		where asset_version=%s and owner=%s and status in ('Open', 'Investigating') for update""",
		(version.name, frappe.session.user),
	)[0][0]
	if open_count >= 100:
		frappe.throw(_("This version already has 100 open reports from you."))

	doc.insert(ignore_permissions=True)
	return _row(doc)


def _row(doc):
	return {
		key: doc.get(key)
		for key in (
			"name",
			"media_project",
			"source_edit",
			"asset_version",
			"shot",
			"scope",
			"start_frame",
			"end_frame",
			"fps",
			"start_seconds",
			"feedback",
			"category",
			"priority",
			"status",
			"admin_response",
			"owner",
			"creation",
		)
	} | {
		"annotation": json.loads(doc.annotation_json) if doc.annotation_json else None,
		"author_name": get_fullname(doc.owner),
	}


@frappe.whitelist()
def get_feedback(
	project_name, asset_version, start=0, page_length=30, focused_name=None, include_closed=True
):
	_root, _asset, version, _shot, fps, limit = target(project_name, asset_version)
	try:
		start, page_length = max(0, int(start)), min(100, max(1, int(page_length)))
	except (TypeError, ValueError):
		frappe.throw(_("Invalid review paging."))
	from joymedia.services.partners import is_reviewer

	filters = {"asset_version": version.name}
	if is_reviewer():
		filters["owner"] = frappe.session.user
	focused_filters = dict(filters)
	if not frappe.utils.cint(include_closed):
		filters["status"] = ["in", ["Open", "Investigating"]]
	rows = frappe.get_all(
		"Video Review Feedback",
		filters=filters,
		order_by="creation asc, name asc",
		limit_start=start,
		limit_page_length=page_length + 1,
		fields=["*"],
	)
	focused = (
		frappe.db.get_value(
			"Video Review Feedback", {**focused_filters, "name": focused_name}, "*", as_dict=True
		)
		if focused_name
		else None
	)
	from joymedia.services.partners import is_reviewer, media_url, policy

	partner = is_reviewer()
	access = policy() if partner else None
	shared = partner and (
		frappe.db.get_value("Media Project", _asset.media_project, "owner") != frappe.session.user
		or not access.allow_generation
	)
	return {
		"allow_feedback": bool(access.allow_feedback) if partner else True,
		"allow_download": bool(access.allow_download) if partner else True,
		"focused": _row(focused) if focused else None,
		"items": [_row(frappe._dict(row)) for row in rows[:page_length]],
		"has_more": len(rows) > page_length,
		"fps": fps,
		"total_frames": limit,
		"file": media_url(version.name) if shared else _get_asset_version_file_url(version.name),
	}


@frappe.whitelist(methods=["POST"])
def triage_feedback(name, status, admin_response=""):
	frappe.only_for("System Manager")
	doc = frappe.get_doc("Video Review Feedback", name)
	doc.status, doc.admin_response = status, admin_response
	doc.save()
	return _row(doc)
