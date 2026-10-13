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
	("Logo", ("logo", "wordmark", "brand mark", "thương hiệu")),
	("Product", ("product", "pack", "package", "box", "bottle", "tube", "label", "sản phẩm", "bịch", "hộp", "gói", "chai")),
	("Character", ("character", "mascot", "person", "model", "actor", "face", "bear", "nhân vật", "gấu", "người", "mẹ", "con")),
)
ROLE_CATEGORY = {"Product": "Product", "Character": "Character", "Logo": "Brand", "Environment": "Background", "General": "Reference"}
ROLES = ("Product", "Character", "Logo", "Environment", "General")


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
def preview_workbook(workbook_file):
	"""What a storyboard workbook will produce, per sheet, before anything is created.

	A workbook can hold several demos; the client picks one and sees its format, length and scene count.
	"""
	from joymedia.services.storyboard_workbook import parse_duration_seconds, parse_storyboard_workbook

	file_doc = frappe.get_doc("File", workbook_file)
	file_doc.check_permission("read")
	if not str(file_doc.file_name or "").lower().endswith(".xlsx"):
		frappe.throw(_("Storyboard import requires an .xlsx workbook."))
	try:
		parsed = parse_storyboard_workbook(file_doc.get_full_path())
	except (OSError, ValueError) as exc:
		frappe.throw(_("Could not read the storyboard workbook: {0}").format(str(exc)))
	demos = []
	for demo in parsed["demos"]:
		metadata = demo.get("metadata") or {}
		demos.append({
			"name": demo["name"],
			"product_name": metadata.get("product_name") or "",
			"format": format_preset(metadata.get("format")),
			"duration_seconds": parse_duration_seconds(metadata.get("duration") or "") if metadata.get("duration") else None,
			"scene_count": len(demo.get("scenes") or []),
			"timing_gaps": len(demo.get("timing_warnings") or []),
		})
	return {"demos": demos}


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
	if format and format not in ("Landscape", "Portrait", "Square") and not format_preset(format):
		frappe.throw(_("Choose Landscape, Portrait or Square."))
	project = create_project(project_name or _("Untitled Project"), "", video_idea or None)
	try:
		if workbook_file:
			summary = import_storyboard_workbook(project.name, workbook_file, demo_name)
			project.reload()
			if not project_name and project.product_name:
				# Name the project after the product and the sheet it was built from.
				project.db_set("project_name", f"{project.product_name} — {summary['demo']}"[:140], update_modified=False)
		if format:
			preset = format if format in ("Landscape", "Portrait", "Square") else format_preset(format)
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
	except Exception:
		# The workbook import commits, so a failure later would leave a half-built project behind.
		frappe.db.rollback()
		for shot in frappe.get_all("Shot", filters={"media_project": project.name}, pluck="name"):
			frappe.delete_doc("Shot", shot, force=True, ignore_permissions=True)
		frappe.delete_doc("Media Project", project.name, force=True, ignore_permissions=True)
		frappe.db.commit()
		raise
	frappe.db.commit()
	return {"project": project.name, "references": added, "readiness": get_project_readiness(project.name)}


@frappe.whitelist()
def get_project_readiness(project_name, lang=None):
	"""What is still needed before this project can be generated, one item per requirement.

	`lang` follows the studio's own language switch (the server only knows the user's saved language).
	"""
	from joymedia.api.storyboard import shot_reference_problems

	if lang in ("vi", "en"):
		frappe.local.lang = lang

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
	# Finished renders are noticed by a cron that runs every minute, but only as often as Frappe's scheduler
	# ticks (4 minutes by default). A slow tick leaves the GPU idle between tasks.
	from frappe.utils.scheduler import get_scheduler_tick

	tick = get_scheduler_tick()
	add(
		"scheduler", _("Background processing"), tick <= 60,
		_("Set scheduler_tick_interval to 60 in common_site_config.json: finished renders are only noticed every {0} seconds.").format(tick)
		if tick > 60 else "",
		blocking=False,
	)
	blocking = [step for step in steps if step["status"] == "todo"]
	return {"ready": not blocking, "steps": steps, "next": blocking[0]["key"] if blocking else None}



def extract_pdf_images(pdf_path, min_side=200, max_images=150):
	"""The usable pictures of a PDF (a product catalogue, a brand book): one dict per picture.

	Each has its page, size, PNG bytes, whether it has real transparency (a cutout can be pasted into a frame;
	an opaque photo can only guide the image model) and the text of its page, which names what it shows.
	Tiny pictures (icons, bullets) and repeats of the same pixels are skipped.
	"""
	import hashlib
	import io

	from PIL import Image
	from pypdf import PdfReader

	reader = PdfReader(str(pdf_path))
	seen, found = set(), []
	for number, page in enumerate(reader.pages, 1):
		try:
			text = " ".join((page.extract_text() or "").split())[:200]
		except Exception:  # an unreadable text layer must not stop the pictures
			text = ""
		for picture in page.images:
			try:
				image = Image.open(io.BytesIO(picture.data))
				image.load()
			except Exception:
				continue
			if min(image.size) < min_side:
				continue
			rgba = image.convert("RGBA")
			digest = hashlib.sha256(rgba.tobytes()).hexdigest()
			if digest in seen:
				continue
			seen.add(digest)
			output = io.BytesIO()
			rgba.save(output, "PNG")
			found.append({
				"page": number, "name": picture.name, "width": rgba.width, "height": rgba.height,
				"has_alpha": rgba.getchannel("A").getextrema()[0] < 250, "page_text": text, "png": output.getvalue(),
			})
			if len(found) >= max_images:
				return found
	return found


@frappe.whitelist()
def add_pdf_images_to_project(project_name, file_name, pages=None):
	"""Add the pictures of an uploaded PDF to a project as references, with roles guessed from each page's text.

	`pages` optionally limits which pages (a list or comma-separated numbers). Returns what was added so the
	client can correct a role in the studio.
	"""
	from joymedia.api.assets import select_project_asset
	from joymedia.services.media_asset_service import create_media_asset

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	wanted = {int(n) for n in (frappe.parse_json(pages) if isinstance(pages, str) and pages.startswith("[") else str(pages or "").split(",")) if str(n).strip()}
	pdf = frappe.get_doc("File", file_name)
	added = []
	for item in extract_pdf_images(pdf.get_full_path()):
		if wanted and item["page"] not in wanted:
			continue
		label = f"{pdf.file_name.rsplit('.', 1)[0][:40]} p{item['page']} {item['name'].rsplit('.', 1)[0]}"
		role = infer_reference_role(item["page_text"]) if item["has_alpha"] else "General"
		image_file = frappe.get_doc({
			"doctype": "File", "file_name": f"{label}.png".replace("/", "-"), "content": item["png"], "is_private": 1,
		}).insert(ignore_permissions=True)
		asset = create_media_asset(label, ROLE_CATEGORY[role], file_url=image_file.file_url, file_name=image_file.name)
		select_project_asset(project.name, asset["media_asset"], role if role != "General" else "General", label)
		added.append({"label": label, "page": item["page"], "role": role, "has_alpha": item["has_alpha"]})
	frappe.db.commit()
	return added
