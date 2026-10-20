"""The workbook's References sheet applied to the project's pictures.

Each row names a picture (a file the client uploads, or a page of a PDF) and says what it is: its name in the script,
its type, a description, a family role, a relative height and what must not change. Rows are matched to the uploaded
pictures by file name (accents, case and extension ignored) or by PDF page, and the matched picture takes the row's
name, role, size and rule. A row without a file is a place the AI draws (see planning.production for its use).
"""

import re
import unicodedata
from pathlib import Path

import frappe
from frappe import _


def sheet_references(project):
	"""The References rows stored from the imported workbook ([] for a project without one)."""
	try:
		return (frappe.parse_json(project.storyboard_source_json or "{}") or {}).get("references") or []
	except (TypeError, ValueError):
		return []


def plain(text):
	"""A name as compared: no accents, no case, no extension, letters and digits only."""
	text = Path(str(text or "").strip()).stem if re.search(r"\.\w{2,4}$", str(text or "").strip()) else str(text or "")
	text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
	return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in text if not unicodedata.combining(c)).casefold()).strip()


def pdf_pages(rows, pdf_file_name):
	"""The pages of an uploaded PDF that the References sheet names (empty: the sheet names none of its pages)."""
	return sorted({row["pdf_page"] for row in rows if row.get("pdf_page") and plain(row.get("file")) == plain(pdf_file_name)})


def _picture_names(project):
	"""{Project Reference row name: (plain file name, plain label)} of the project's pictures."""
	names = {}
	for row in project.selected_media or []:
		file_url = frappe.db.get_value("Asset Version", row.asset_version, "file") if row.asset_version else None
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "file_name") if file_url else ""
		names[row.name] = (plain(file_name), plain(row.label))
	return names


def _match(row, project, names):
	"""The project's picture for a References row, or None."""
	if not row.get("file"):
		return None
	wanted = plain(row["file"])
	if row.get("pdf_page"):
		# A PDF's pictures are labelled "<pdf name> p<page> <image>" (intake.project.add_pdf_images_to_project).
		page = [
			reference for reference in project.selected_media or []
			if plain(reference.label).startswith(wanted[:40].strip()) and f" p{row['pdf_page']} " in f" {plain(reference.label)} "
		]
		# Several pictures on one page: the largest is the subject (the others are icons and decorations).
		return max(page, key=lambda reference: _picture_area(reference.asset_version), default=None)
	matched = next((reference for reference in project.selected_media or [] if wanted in names.get(reference.name, ())), None)
	if matched:
		return matched
	# Private uploads may receive a hash suffix. An explicitly selected, uniquely
	# named reference still matches the sheet; never guess from a partial filename.
	labelled = [reference for reference in project.selected_media or []
	            if plain(str(reference.label or "").split(" (")[0]) == plain(row.get("name"))]
	return labelled[0] if len(labelled) == 1 else None


def _picture_area(asset_version):
	from PIL import Image

	file_url = frappe.db.get_value("Asset Version", asset_version, "file")
	try:
		with Image.open(frappe.get_doc("File", {"file_url": file_url}).get_full_path()) as picture:
			return picture.width * picture.height
	except Exception:
		return 0


def apply_sheet_references(project_name):
	"""Give each picture the References sheet names its name, role, size and rule. Returns {matched, missing}."""
	from joymedia.services.planning.roles import role_size

	project = frappe.get_doc("Media Project", project_name)
	rows = sheet_references(project)
	if not rows:
		return {"matched": [], "missing": []}
	names = _picture_names(project)
	matched, missing, changed = [], [], False
	for row in rows:
		reference = _match(row, project, names)
		if not reference:
			if row.get("file"):
				missing.append(row["name"])
			continue
		label = row["name"] + (f" ({row['description']})" if row.get("description") else "")
		size = row.get("relative_size") or (role_size(f"{row['name']} {row.get('family_role') or ''}") if row["role"] == "Character" else None)
		# A prop's picture is kept for the record; props reach the prompts by their description (planning.production).
		role = {"General": reference.reference_role, "Prop": "General"}.get(row["role"], row["role"])
		values = {"label": label[:140], "reference_role": role,
		          "relative_size": size or reference.relative_size, "keep_rule": row.get("keep_rule") or ""}
		if any((reference.get(key) or None) != (value or None) for key, value in values.items()):
			reference.update(values)
			changed = True
		matched.append(row["name"])
	if changed:
		project.save(ignore_permissions=True)
	return {"matched": matched, "missing": missing}


def missing_pictures(project):
	"""Names of References rows whose picture the project does not have."""
	rows = sheet_references(project)
	if not rows:
		return []
	names = _picture_names(project)
	return [row["name"] for row in rows if row.get("file") and not _match(row, project, names)]


def preservation_modes(project):
	"""Explicit workbook choices by immutable reference version; absent means strict default."""
	names, modes = _picture_names(project), {}
	for row in sheet_references(project):
		mode = row.get("preservation_mode")
		if not mode:
			continue
		if mode not in {"source_pixels", "reference_guided"}:
			raise ValueError("Unsupported reference preservation mode.")
		ref = _match(row, project, names)
		if ref:
			if ref.asset_version in modes and modes[ref.asset_version] != mode:
				raise ValueError("The same reference has conflicting preservation modes.")
			modes[ref.asset_version] = mode
	return modes


def find_reference(name, references):
	"""The project reference option ({key, label, role}) a script name refers to, or None."""
	wanted = plain(name)
	if not wanted:
		return None
	exact = [r for r in references if plain(str(r["label"]).split(" (")[0]) == wanted or plain(r.get("key")) == wanted
		or any(plain(str(alias).split(" (")[0]) == wanted for alias in r.get("aliases", []))]
	if exact:
		return exact[0]
	return next((r for r in references if wanted in plain(r["label"])), None)


def props_in(text, project):
	"""The References sheet's props whose name the text uses: [(name, description)]."""
	words = f" {plain(text)} "
	return [
		(row["name"], row.get("description") or "")
		for row in sheet_references(project)
		if row["role"] == "Prop" and plain(row["name"]) and f" {plain(row['name'])} " in words
	]


def brand(project):
	"""The workbook's Brand sheet as stored ({} for a project without one)."""
	try:
		return (frappe.parse_json(project.storyboard_source_json or "{}") or {}).get("brand") or {}
	except (TypeError, ValueError):
		return {}


def place_row(name, project):
	"""The References row of a place by its name (a place the AI draws has no picture), or None."""
	wanted = plain(name)
	return next((row for row in sheet_references(project) if row["role"] == "Environment" and plain(row["name"]) == wanted), None)


def missing_detail(names):
	return _("The References sheet names these pictures, but they are not uploaded: {0}.").format(", ".join(names))
