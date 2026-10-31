"""Restore the selected Shera/Auntie snapshot, without starting jobs or inference."""

import hashlib
import json
import shutil
from pathlib import Path

import frappe
from frappe.utils import cint

DATA = Path(__file__).parent
PREFIX = "JM-DEMO-"
ALLOWED = {
	"Media Project",
	"Project Reference",
	"Shot",
	"Shot Reference",
	"Timeline Clip",
	"Media Asset",
	"Asset Version",
	"Generation Workflow",
	"Workflow Binding",
	"Generation Pipeline",
	"Generation Pipeline Step",
	"File",
}
IDENTITY = (
	"owner",
	"parent",
	"parenttype",
	"parentfield",
	"version_of",
	"media_project",
	"media_asset",
	"file_url",
)


def flatten(rows, parent=None, parentfield=None):
	"""Flatten only named child tables, preserving IDs, idx and authored ordering."""
	for row in rows:
		values = {k: v for k, v in row.items() if not isinstance(v, list)}
		if parent:
			values.update(parent=parent["name"], parenttype=parent["doctype"], parentfield=parentfield)
		yield values
		for key, children in row.items():
			if isinstance(children, list):
				yield from flatten(children, row, key)


def digest(path):
	with path.open("rb") as stream:
		return hashlib.file_digest(stream, "sha256").hexdigest()


def read_bundle():
	manifest = json.loads((DATA / "manifest.json").read_text())
	rows = list(flatten(json.loads((DATA / "records.json").read_text())))
	return manifest, rows


def validate_bundle(rows, manifest):
	"""Check schema, private files, and all Links before restoring a cyclic graph."""
	keys = {(row["doctype"], row["name"]) for row in rows}
	if len(keys) != len(rows):
		raise ValueError("Duplicate IDs in demo bundle")
	urls = {item["file_url"] for item in manifest["media"]}
	for row in rows:
		if row["doctype"] not in ALLOWED or not row["name"].startswith(PREFIX):
			raise ValueError("Unexpected demo record")
		if row.get("owner") != "Administrator" or row.get("modified_by") != "Administrator":
			raise ValueError("Demo must not restore original user identities")
		meta = frappe.get_meta(row["doctype"])
		columns = set(meta.get_valid_columns()) | {"doctype"}
		if set(row) - columns:
			raise ValueError(f"Schema mismatch: {row['doctype']}: {sorted(set(row) - columns)}")
		for field in meta.fields:
			value = row.get(field.fieldname)
			if not value:
				continue
			if field.fieldtype == "Password":
				raise ValueError("Passwords are not allowed in demo records")
			if field.fieldtype == "Link" and (field.options, value) not in keys:
				raise ValueError(f"Unresolved demo link: {row['doctype']}.{field.fieldname}")
			if field.fieldtype in {"Attach", "Attach Image"} and value not in urls:
				raise ValueError(f"Unresolved demo media: {row['name']}")
		if meta.istable and (row.get("parenttype"), row.get("parent")) not in keys:
			raise ValueError(f"Unresolved child parent: {row['name']}")
		if row["doctype"] == "File" and (row.get("file_url") not in urls or row.get("is_private") != 1):
			raise ValueError("All bundled files must use the private media manifest")
	return keys


def media_paths(manifest):
	result = []
	for item in manifest["media"]:
		name = Path(item["path"]).name
		if item["path"] != f"media/{name}" or not name.startswith("jm-demo-"):
			raise ValueError("Unsafe media path")
		if item["file_url"] != f"/private/files/{name}":
			raise ValueError("Unsafe media URL")
		source = (DATA / item["path"]).resolve()
		if not source.is_relative_to((DATA / "media").resolve()) or not source.is_file():
			raise ValueError(f"Missing demo media: {name}")
		if source.stat().st_size != item["bytes"] or digest(source) != item["sha256"]:
			raise ValueError(f"Demo media checksum mismatch: {name}")
		destination = Path(frappe.get_site_path("private", "files", name))
		if destination.is_symlink():
			raise ValueError(f"Refusing media symlink: {name}")
		if destination.exists() and digest(destination) != item["sha256"]:
			raise ValueError(f"Existing media collision: {name}")
		result.append((source, destination))
	return result


def load():
	"""Restore a vetted snapshot with direct DB inserts, keeping historical timing.

	This is deliberately a restore, not Document.insert: controller hooks would
	renumber immutable versions and recalculate a historical timeline. Validate
	all schema and Links first, then insert the entire graph in one transaction.
	Bench execute commits; rollback also removes newly copied files.
	"""
	if frappe.session.user != "Administrator":
		frappe.throw("Only Administrator may load handover data.", frappe.PermissionError)
	if not cint(frappe.conf.get("joymedia_allow_demo_data")):
		frappe.throw("Enable joymedia_allow_demo_data on the demo site first.")
	manifest, rows = read_bundle()
	validate_bundle(rows, manifest)
	paths = media_paths(manifest)
	existing = []
	for row in rows:
		if frappe.db.exists(row["doctype"], row["name"]):
			doc = frappe.get_doc(row["doctype"], row["name"])
			if any((doc.get(key) or None) != (row.get(key) or None) for key in IDENTITY):
				frappe.throw(f"Demo ID collision: {row['doctype']} {row['name']}")
			existing.append(row["name"])
	if existing and len(existing) != len(rows):
		frappe.throw("Partial demo dataset detected; restore into a clean demo site.")
	created_files = []

	def cleanup():
		for path in created_files:
			path.unlink(missing_ok=True)

	frappe.db.savepoint("joymedia_demo_seed")
	try:
		for source, destination in paths:
			if not destination.exists():
				destination.parent.mkdir(parents=True, exist_ok=True)
				# Exclusive creation never overwrites another file.
				with destination.open("xb") as stream:
					created_files.append(destination)
					with source.open("rb") as incoming:
						shutil.copyfileobj(incoming, stream)
				destination.chmod(0o600)
		if not existing:
			for row in rows:
				frappe.get_doc(row).db_insert()
		frappe.db.after_rollback.add(cleanup)
	except Exception:
		frappe.db.rollback(save_point="joymedia_demo_seed")
		cleanup()
		raise
	return {
		"dataset": manifest["dataset"],
		"created": 0 if existing else len(rows),
		"skipped": len(existing),
		"projects": 2,
		"videos": 3,
		"media_files": len(paths),
	}
