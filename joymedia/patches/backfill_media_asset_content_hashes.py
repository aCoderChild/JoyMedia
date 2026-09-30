import hashlib
from pathlib import Path

import frappe


def execute():
	for asset in frappe.get_all("Media Asset", fields=["name"]):
		if frappe.db.get_value("Media Asset", asset.name, "content_hash"):
			continue

		file_url = frappe.db.get_value(
			"Asset Version",
			{"media_asset": asset.name},
			"file",
			order_by="version_number desc",
		)
		if not file_url:
			continue
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not file_name:
			continue
		file_path = Path(frappe.get_doc("File", file_name).get_full_path())
		if not file_path.is_file():
			continue

		digest = hashlib.sha256()
		with file_path.open("rb") as file_handle:
			for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
				digest.update(chunk)
		frappe.db.set_value("Media Asset", asset.name, "content_hash", digest.hexdigest(), update_modified=False)
