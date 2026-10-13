"""Client intake: turn a brief or workbook plus reference images into a ready-to-review project.

A client should only have to supply the story (a storyboard workbook or a written brief) and the
images the film depends on. Everything else is derived: the format and duration from the workbook,
each reference's role from its name, the workflow from the promoted pipeline, and which references
each scene needs from the planner. `get_project_readiness` tells the client what is still missing
before generation, instead of the failure appearing at render time.
"""

import re

import frappe
from frappe import _

# Words that mark what a reference image is, in English and Vietnamese. Order matters: first match wins.
ROLE_KEYWORDS = (
	("Environment", ("environment", "background", "location", "room", "interior", "setting", "scene", "phòng", "bối cảnh", "nền", "không gian")),
	("Product", ("product", "pack", "package", "box", "bottle", "tube", "label", "logo", "sản phẩm", "bịch", "hộp", "gói", "chai")),
	("Character", ("character", "mascot", "person", "model", "actor", "face", "bear", "nhân vật", "gấu", "người", "mẹ", "con")),
)
ROLE_CATEGORY = {"Product": "Product", "Character": "Character", "Environment": "Background", "General": "Reference"}
ROLES = ("Product", "Character", "Environment", "General")


def infer_reference_role(name):
	"""Best guess of a reference's role from its name; General when nothing matches."""
	text = str(name or "").casefold()
	for role, words in ROLE_KEYWORDS:
		if any(word in text for word in words):
			return role
	return "General"


def format_preset(text):
	"""Delivery preset for the first aspect ratio found in a format description, else None."""
	match = re.search(r"(\d+)\s*[:x×]\s*(\d+)", str(text or ""))
	if not match:
		return None
	width, height = int(match.group(1)), int(match.group(2))
	if not width or not height:
		return None
	ratio = width / height
	return "Portrait" if ratio < 0.9 else "Square" if ratio <= 1.1 else "Landscape"


def apply_workbook_format(project):
	"""Set the project's delivery format and duration from the imported workbook's own metadata."""
	try:
		demo = (frappe.parse_json(project.storyboard_source_json or "{}") or {}).get("selected_demo") or {}
	except (TypeError, ValueError):
		return None
	preset = format_preset((demo.get("metadata") or {}).get("format"))
	duration = float(project.total_duration_seconds or 0)
	if preset and 1 <= duration <= 60:
		project.save_video_settings(total_duration_seconds=duration, delivery_preset=preset)
	return preset


@frappe.whitelist()
def create_project_from_brief(project_name=None, video_idea=None, workbook_file=None, demo_name=None, references=None, format=None):
	"""Create a project from the client's inputs and report what is still missing.

	references: list of {file_name, label, role}; role may be empty (inferred from the label).
	"""
	from joymedia.api.projects import create_project
	from joymedia.api.assets import select_project_asset
	from joymedia.api.storyboard import import_storyboard_workbook
	from joymedia.services.media_asset_service import create_media_asset

	references = frappe.parse_json(references) if isinstance(references, str) else (references or [])
	if not isinstance(references, list):
		frappe.throw(_("References must be a list."))
	project = create_project(project_name or _("Untitled Project"), "", video_idea or None)
	if workbook_file:
		import_storyboard_workbook(project.name, workbook_file, demo_name)
		project.reload()
	if format:
		preset = format if format in ("Landscape", "Portrait", "Square") else format_preset(format)
		if not preset:
			frappe.throw(_("Choose Landscape, Portrait or Square."))
		project.save_video_settings(total_duration_seconds=project.total_duration_seconds or 15, delivery_preset=preset)
	added = []
	for item in references:
		label = str(item.get("label") or "").strip() or str(item.get("file_name") or "reference")
		# Without a role the Project Reference controller classifies the image from its label.
		role = item.get("role") if item.get("role") in ROLES else infer_reference_role(label)
		file_doc = frappe.get_doc("File", item["file_name"])
		asset = create_media_asset(label, ROLE_CATEGORY[role], file_url=file_doc.file_url, file_name=file_doc.name)
		select_project_asset(project.name, asset["media_asset"], role if item.get("role") in ROLES else "General", label)
		added.append({"label": label, "role": role})
	frappe.db.commit()
	return {"project": project.name, "references": added, "readiness": get_project_readiness(project.name)}


@frappe.whitelist()
def get_project_readiness(project_name):
	"""What is still needed before this project can be generated, one item per requirement."""
	from joymedia.api.storyboard import shot_reference_problems

	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	shots = frappe.get_all("Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name")
	steps = []

	def add(key, label, ok, detail="", blocking=True):
		steps.append({"key": key, "label": label, "status": "done" if ok else ("todo" if blocking else "note"), "detail": detail})

	add("story", _("Story or storyboard"), bool(shots), "" if shots else _("Import a storyboard workbook or generate a storyboard from the brief."))
	add(
		"format", _("Video format"), bool(project.delivery_width and project.delivery_height),
		f"{project.delivery_preset} {project.delivery_width}×{project.delivery_height}, {float(project.total_duration_seconds or 0):g}s"
		if project.delivery_width else _("Choose Landscape, Portrait or Square."),
	)
	references = [row for row in project.selected_media or [] if row.reference_key]
	add("references", _("Reference images"), bool(references), ", ".join(f"{r.label or r.reference_key} ({r.reference_role})" for r in references) or _("Add the images the film must show (a character, a product…)."), blocking=False)
	problems = shot_reference_problems(project) if shots and project.workflow else []
	add("assignments", _("Each scene's references"), not problems, "; ".join(problems[:3]) if problems else "")
	warnings = frappe.parse_json(project.storyboard_timing_warnings or "[]")
	add("timing", _("Storyboard timing"), not warnings, _("{0} timing gap(s) were found; they are closed on export.").format(len(warnings)) if warnings else "", blocking=False)
	add("approval", _("Storyboard approved"), project.storyboard_approval_status == "Approved", "" if project.storyboard_approval_status == "Approved" else _("Review the scenes, then approve."))
	blocking = [step for step in steps if step["status"] == "todo"]
	return {"ready": not blocking, "steps": steps, "next": blocking[0]["key"] if blocking else None}
