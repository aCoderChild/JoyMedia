"""Export only the three selected review videos; never mutate the source site."""

import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import frappe

SELECTED = {"PRJ-02558": 14, "PRJ-02586": 33, "PRJ-02563": 5}
ROOTS = {"PRJ-02501": "PRJ-02586", "PRJ-02559": "PRJ-02563"}
PREFIX = "JM-DEMO-"
ALLOWED = {
	"Media Project",
	"Shot",
	"Timeline Clip",
	"Media Asset",
	"Asset Version",
	"Generation Workflow",
	"Generation Pipeline",
	"File",
}
JSON_FIELDS = {
	"workflow_json",
	"execution_spec",
	"motion_plan_json",
	"storyboard_source_json",
	"storyboard_timing_warnings",
}
CLEAR = {
	"approved_plan_signature",
	"brand_approval_signature",
	"brand_approved_by",
	"brand_approved_at",
	"keyframe_artifact",
	"keyframe_status",
	"keyframe_signature",
	"consistency_notes",
	"consistency_status",
	"source_generation_attempt",
	"finished_timeline_signature",
	"post_production_comfy_prompt_id",
	"export_error",
	"post_production_error",
	"planning_error",
	"analysis_error",
	"archived_on",
}


def export_selected():
	if frappe.session.user != "Administrator":
		frappe.throw("Only Administrator may export the selected demo.", frappe.PermissionError)
	out = Path(__file__).parent
	media = out / "media"
	media.mkdir(exist_ok=True)
	docs, files, urls = {}, {}, {}
	queue = [("Media Project", n) for n in [*ROOTS, *SELECTED]]
	for name in SELECTED:
		for dt in ("Shot", "Timeline Clip"):
			filters = {"media_project": name}
			if dt == "Shot":
				filters["is_removed"] = 0
			queue.extend((dt, n) for n in frappe.get_all(dt, filters=filters, pluck="name", order_by="name"))

	def visit(doc):
		meta = frappe.get_meta(doc.doctype)
		row = {
			"doctype": doc.doctype,
			"name": doc.name,
			"owner": "Administrator",
			"modified_by": "Administrator",
			"creation": "2026-10-31 00:00:00",
			"modified": "2026-10-31 00:00:00",
			"docstatus": 0,
			"idx": doc.idx or 0,
		}
		for field in meta.fields:
			key, value = field.fieldname, doc.get(field.fieldname)
			if field.fieldtype in {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}:
				continue
			if key in CLEAR or field.fieldtype == "Password" or field.options == "User":
				continue
			if field.fieldtype in {"JSON", "Code"} and key not in JSON_FIELDS:
				continue
			if field.fieldtype in {"Table", "Table MultiSelect"}:
				row[key] = [visit(child) for child in value or []]
				continue
			row[key] = value
		if doc.doctype == "Media Project":
			row.update(
				planning_status="Idle",
				post_production_status="Idle",
				export_status="Idle",
				storyboard_approval_status="Ready for Review",
				current_edit=None,
				version_kind="Creative",
			)
			if doc.name in ROOTS:
				row.update(current_edit=ROOTS[doc.name], current_output_asset_version=None, status="Draft")
			elif doc.name in SELECTED:
				row.update(
					source_video_number=SELECTED[doc.name],
					version_label=f"Video {SELECTED[doc.name]}",
					status="Completed",
					export_status="Completed",
				)
			else:
				raise ValueError("Unexpected project dependency")
		if doc.doctype == "Media Asset" and row.get("media_project") not in {*ROOTS, *SELECTED}:
			# Historic sources are reference media, not additional project families.
			row.update(media_project=None, asset_scope="Library")
		if doc.doctype == "Asset Version":
			row.update(analysis_status="Not Analyzed")
		if doc.doctype == "File":
			path = Path(doc.get_full_path()).resolve()
			site = Path(frappe.get_site_path()).resolve()
			if not path.is_relative_to(site) or not path.is_file():
				raise ValueError(f"Missing/nonlocal media: {doc.name}")
			digest = hashlib.sha256(path.read_bytes()).hexdigest()
			ext = path.suffix.lower()
			if not re.fullmatch(r"\.[a-z0-9]{1,8}", ext):
				raise ValueError(f"Unexpected media extension: {doc.name}")
			filename = f"jm-demo-{digest}{ext}"
			url = f"/private/files/{filename}"
			shutil.copyfile(path, media / filename)
			urls[doc.file_url] = url
			files[filename] = {
				"path": f"media/{filename}",
				"file_url": url,
				"sha256": digest,
				"bytes": path.stat().st_size,
			}
			row = {
				**{
					k: row[k]
					for k in (
						"doctype",
						"name",
						"owner",
						"modified_by",
						"creation",
						"modified",
						"docstatus",
						"idx",
					)
				},
				"file_name": filename,
				"file_url": url,
				"is_private": 1,
				"is_folder": 0,
				"file_size": path.stat().st_size,
				"content_hash": doc.content_hash,
				"file_type": doc.file_type,
			}
		for field in meta.fields:
			value = row.get(field.fieldname)
			if not value:
				continue
			if field.fieldtype == "Link":
				if field.options not in ALLOWED:
					raise ValueError(f"Unexpected link: {doc.doctype}.{field.fieldname} -> {field.options}")
				queue.append((field.options, value))
			if field.fieldtype in {"Attach", "Attach Image"}:
				file_name = frappe.db.get_value("File", {"file_url": value}, "name")
				if not file_name:
					raise ValueError(f"Missing File record for {doc.doctype}.{field.fieldname}")
				queue.append(("File", file_name))
		return row

	while queue:
		dt, name = queue.pop(0)
		if (dt, name) in docs:
			continue
		if dt not in ALLOWED:
			raise ValueError(f"Unexpected dependency: {dt}")
		docs[dt, name] = visit(frappe.get_doc(dt, name))

	def child_rows(rows):
		for row in rows:
			yield row
			for value in row.values():
				if isinstance(value, list):
					yield from child_rows(value)

	rows = list(docs.values())
	mapping = {row["name"]: PREFIX + row["name"] for row in child_rows(rows)}
	mapping.update(urls)
	pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))

	def rewrite(value):
		if isinstance(value, dict):
			return {k: rewrite(v) for k, v in value.items()}
		if isinstance(value, list):
			return [rewrite(v) for v in value]
		if isinstance(value, str):
			return pattern.sub(lambda match: mapping[match.group()], value)
		return value

	rows = rewrite(rows)
	# Bounded snapshot: no runs, tasks, attempts, reviews or original user identities.
	(out / "records.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str) + "\n")
	manifest = {
		"dataset": "shera-auntie-selected-v1",
		"prefix": PREFIX,
		"projects": [{"name": PREFIX + n, "working_edit": PREFIX + e} for n, e in ROOTS.items()],
		"videos": [
			{"source_project": n, "name": PREFIX + n, "number": number} for n, number in SELECTED.items()
		],
		"counts": dict(Counter(row["doctype"] for row in child_rows(rows))),
		"media": list(sorted(files.values(), key=lambda x: x["path"])),
		"omitted": [
			"User accounts and credentials",
			"Generation jobs and attempt history",
			"Historic approvals and release evidence",
			"Unselected project edits",
		],
	}
	(out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
	# Remove only unreferenced files in this dedicated generated dataset directory.
	for path in media.iterdir():
		if path.name not in files:
			path.unlink()
	return {
		"counts": manifest["counts"],
		"media_files": len(files),
		"media_bytes": sum(f["bytes"] for f in files.values()),
	}
