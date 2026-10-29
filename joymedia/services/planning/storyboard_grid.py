"""Import a supplied storyboard grid without invoking a planner or renderer."""

import hashlib
import io
import json
import math
from pathlib import Path

import frappe
from frappe import _
from PIL import Image, ImageOps

from joymedia.services.planning.durations import ensure_shot_planning_editable


def grid_boxes(width, height, rows, columns):
	"""Integer boundaries include the right and bottom edges of non-divisible sheets."""
	if not (1 <= rows <= 6 and 1 <= columns <= 6 and width >= columns and height >= rows):
		raise ValueError("Choose a grid from 1×1 to 6×6 that fits the image.")
	return [
		(c * width // columns, r * height // rows, (c + 1) * width // columns, (r + 1) * height // rows)
		for r in range(rows)
		for c in range(columns)
	]


def _lock_project(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	frappe.db.sql("select name from `tabMedia Project` where name=%s for update", project.name)
	project.reload()
	ensure_shot_planning_editable(project.name)
	if any(
		project.get(field) in ("Queued", "Running") for field in ("export_status", "post_production_status")
	):
		frappe.throw(_("Wait for editing and export jobs to finish before changing scenes."))
	return project


def _append_shots(project, count, seconds):
	old = frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		fields=["name", "shot_number", "duration_seconds", "planned_frame_count"],
		order_by="shot_number asc",
	)
	fps = (
		float(frappe.db.get_value("Generation Workflow", project.workflow, "output_fps") or 24)
		if project.workflow
		else 24
	)
	total = sum(float(row.duration_seconds or 0) for row in old) + count * seconds
	project.db_set("total_duration_seconds", total, update_modified=False)
	created = []
	for index in range(count):
		number = max((row.shot_number for row in old), default=0) + index + 1
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": project.name,
				"shot_number": number,
				"shot_name": _("Scene {0}").format(number),
				"duration_seconds": seconds,
				"planned_frame_count": round(seconds * fps),
				"continuity_mode": "New Scene",
				"generation_prompt": _("Describe the action for this scene before generating."),
			}
		)
		shot.flags.preserve_authored_timing = True
		shot.insert(ignore_permissions=True)
		created.append(shot)
	# Insertion hooks can redistribute timing. Preserve the authored existing edit.
	for row in old:
		frappe.db.set_value(
			"Shot",
			row.name,
			{
				"duration_seconds": row.duration_seconds,
				"planned_frame_count": row.planned_frame_count,
			},
			update_modified=False,
		)
	for shot in created:
		frappe.db.set_value(
			"Shot",
			shot.name,
			{
				"duration_seconds": seconds,
				"planned_frame_count": round(seconds * fps),
			},
			update_modified=False,
		)
	project.db_set("total_duration_seconds", total, update_modified=False)
	return created


@frappe.whitelist(methods=["POST"])
def add_blank_scene(project_name, duration_seconds=5):
	try:
		seconds = float(duration_seconds)
	except (TypeError, ValueError):
		frappe.throw(_("Scene duration must be between 1 and 30 seconds."))
	if not math.isfinite(seconds) or not 1 <= seconds <= 30:
		frappe.throw(_("Scene duration must be between 1 and 30 seconds."))
	project = _lock_project(project_name)
	shot = _append_shots(project, 1, seconds)[0]
	from joymedia.api.storyboard import _mark_storyboard_needs_review

	_mark_storyboard_needs_review(project)
	return {"shot": shot.name}


@frappe.whitelist(methods=["POST"])
def update_scene(
	project_name,
	shot_name,
	title,
	description,
	duration_seconds,
	continuity="New Scene",
	caption="",
	expected_modified=None,
	description_changed=True,
):
	"""Save an authored scene without redistributing neighboring scene timings."""
	from frappe.utils import get_datetime

	from joymedia.api.storyboard import _mark_storyboard_needs_review, update_project_shot

	project = _lock_project(project_name)
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name or shot.is_removed:
		frappe.throw(_("Choose an active scene from this project."), frappe.PermissionError)
	if expected_modified and get_datetime(expected_modified) != get_datetime(shot.modified):
		frappe.throw(_("This scene changed elsewhere. Reload the storyboard before saving your changes."))
	title, description, caption = (
		str(title or "").strip(),
		str(description or "").strip(),
		str(caption or "").strip(),
	)
	if not title or len(title) > 140 or not description or len(description) > 8000 or len(caption) > 120:
		frappe.throw(
			_(
				"Enter a scene name (up to 140 characters), description (up to 8000), and optional caption (up to 120)."
			)
		)
	try:
		seconds = float(duration_seconds)
	except (TypeError, ValueError):
		frappe.throw(_("Scene duration must be between 1 and 60 seconds."))
	if not math.isfinite(seconds) or not 1 <= seconds <= 60:
		frappe.throw(_("Scene duration must be between 1 and 60 seconds."))
	# Reuse the normal prompt/continuity validation and approval invalidation.
	values = {"continuity_mode": continuity, "caption": caption}
	if str(description_changed).lower() in ("1", "true", "yes", "on"):
		values.update(generation_prompt=description, storyboard_action=description, image_prompt=description)
	update_project_shot(project.name, shot.name, values)
	shot.reload()
	fps = (
		float(frappe.db.get_value("Generation Workflow", project.workflow, "output_fps") or 24)
		if project.workflow
		else 24
	)
	frames = round(seconds * fps)
	if shot.duration_seconds != frames / fps:
		shot.motion_plan_json = None
	shot.shot_name, shot.duration_seconds, shot.planned_frame_count = title, frames / fps, frames
	shot.flags.preserve_authored_timing = True
	shot.save(ignore_permissions=True)
	total = (
		frappe.db.sql(
			"select sum(duration_seconds) from `tabShot` where media_project=%s and is_removed=0",
			project.name,
		)[0][0]
		or 0
	)
	project.db_set("total_duration_seconds", total, update_modified=False)
	_mark_storyboard_needs_review(project)
	return {
		"name": shot.name,
		"title": shot.shot_name,
		"description": description,
		"duration": shot.duration_seconds,
		"continuity": shot.continuity_mode,
		"caption": shot.caption or "",
		"modified": str(shot.modified),
		"total_duration_seconds": total,
	}


@frappe.whitelist(methods=["POST"])
def import_grid(project_name, file_name, rows=3, columns=4, mode="append", request_id=None):
	"""Append all panels or replace matching scene frames atomically; retry-safe."""
	from joymedia.api.storyboard import set_project_shot_keyframe

	project = _lock_project(project_name)
	if mode not in ("append", "existing"):
		frappe.throw(_("Choose append scenes or replace existing scene images."))
	if not request_id or len(str(request_id)) > 100:
		frappe.throw(_("A valid import request ID is required."))
	try:
		r, c = int(rows), int(columns)
		if float(rows) != r or float(columns) != c:
			raise ValueError
	except (TypeError, ValueError):
		frappe.throw(_("Rows and columns must be whole numbers."))
	source = frappe.get_doc("File", file_name)
	source.check_permission("read")
	if source.owner != frappe.session.user and frappe.session.user != "Administrator":
		frappe.throw(_("Use a storyboard image uploaded by your account."), frappe.PermissionError)
	try:
		content = Path(source.get_full_path()).read_bytes()
	except OSError:
		frappe.throw(_("The uploaded storyboard image is no longer available. Upload it again."))
	fingerprint = hashlib.sha256(content + f"|{r}|{c}|{mode}".encode()).hexdigest()
	history = json.loads(project.get("storyboard_grid_imports_json") or "{}")
	if str(request_id) in history:
		previous = history[str(request_id)]
		if previous["fingerprint"] != fingerprint:
			frappe.throw(_("This import ID was already used with different settings."))
		return previous["result"]
	try:
		with Image.open(io.BytesIO(content)) as original:
			if original.width * original.height > 40_000_000:
				raise ValueError("Storyboard image exceeds 40 megapixels.")
			image = ImageOps.exif_transpose(original).convert("RGB")
		boxes = grid_boxes(image.width, image.height, r, c)
	except (OSError, ValueError, Image.DecompressionBombError) as exc:
		frappe.throw(_("Cannot slice this storyboard: {0}").format(str(exc)))
	shots = frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		pluck="name",
		order_by="shot_number asc",
	)
	if mode == "existing" and len(shots) != len(boxes):
		frappe.throw(
			_(
				"Replacing frames requires exactly one panel per existing scene. Choose append to import every panel."
			)
		)
	if mode == "append":
		shots = [shot.name for shot in _append_shots(project, len(boxes), 5)]
	versions = []
	for index, box in enumerate(boxes):
		label = _("Storyboard panel {0}").format(index + 1)
		buffer = io.BytesIO()
		image.crop(box).save(buffer, format="PNG")
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"storyboard-{frappe.generate_hash(length=10)}-{index + 1}.png",
				"content": buffer.getvalue(),
				"attached_to_doctype": "Media Project",
				"attached_to_name": project.name,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": label,
				"media_type": "Image",
				"asset_category": "Reference",
				"asset_scope": "Library",
				"status": "Active",
				"owner": project.owner,
			}
		).insert(ignore_permissions=True)
		version = frappe.get_doc(
			{
				"doctype": "Asset Version",
				"media_asset": asset.name,
				"file": file.file_url,
				"source": "Uploaded",
				"owner": project.owner,
			}
		).insert(ignore_permissions=True)
		project.append(
			"selected_media", {"asset_version": version.name, "reference_role": "Composition", "label": label}
		)
		versions.append(version.name)
	project.save(ignore_permissions=True)
	for shot, version in zip(shots, versions, strict=True):
		set_project_shot_keyframe(project.name, shot, "first_frame", version)
	result = {"shots": shots, "panels": len(boxes), "mode": mode}
	history[str(request_id)] = {"fingerprint": fingerprint, "result": result}
	project.db_set(
		"storyboard_grid_imports_json", json.dumps(dict(list(history.items())[-20:])), update_modified=False
	)
	return result
