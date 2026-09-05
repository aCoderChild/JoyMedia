import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import now


def compose_video(composition_name: str):
	composition = frappe.get_doc("Media Composition", composition_name)
	if composition.transition_mode != "Cut":
		frappe.throw(_("Only Cut transition mode is supported."))
	if not composition.composition_items:
		frappe.throw(_("Media Composition requires at least one Composition Item."))

	items = sorted(composition.composition_items, key=lambda item: item.sequence_order)
	paths = [_get_asset_version_path(item.asset_version) for item in items]
	composition.status = "Processing"
	composition.save(ignore_permissions=True)

	try:
		with tempfile.TemporaryDirectory() as temp_dir:
			concat_file = Path(temp_dir) / "inputs.txt"
			output_file = Path(temp_dir) / f"{composition.name}.mp4"
			concat_file.write_text(
				"\n".join(f"file '{_escape_concat_path(path)}'" for path in paths) + "\n"
			)
			subprocess.run(
				[
					"ffmpeg",
					"-y",
					"-f",
					"concat",
					"-safe",
					"0",
					"-i",
					str(concat_file),
					"-c",
					"copy",
					str(output_file),
				],
				capture_output=True,
				text=True,
				check=True,
			)
			video_bytes = output_file.read_bytes()
	except (OSError, subprocess.CalledProcessError) as exc:
		composition.status = "Failed"
		composition.save(ignore_permissions=True)
		frappe.throw(_("Unable to compose video: {0}").format(str(exc)))

	media_spec = frappe.get_doc("Media Specification", composition.media_specification)
	asset_name = f"{composition.name} Composed Video"
	asset_id = frappe.db.get_value("Media Asset", {"asset_name": asset_name}, "name")
	if asset_id:
		output_asset = frappe.get_doc("Media Asset", asset_id)
	else:
		output_asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": asset_name,
				"asset_scope": "Project",
				"media_type": "Video",
				"asset_category": "Final Deliverable",
				"media_project": media_spec.media_project,
			}
		)
		output_asset.insert(ignore_permissions=True)

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{composition.name}.mp4",
			"content": video_bytes,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": output_asset.name,
		}
	)
	file_doc.insert(ignore_permissions=True)

	asset_version = frappe.get_doc(
		{
			"doctype": "Asset Version",
			"media_asset": output_asset.name,
			"file": file_doc.file_url,
			"source": "Composed",
		}
	)
	asset_version.insert(ignore_permissions=True)

	composition.output_asset_version = asset_version.name
	composition.status = "Completed"
	composition.save(ignore_permissions=True)
	return {"status": composition.status, "output_asset_version": asset_version.name, "completed_at": now()}


def _get_asset_version_path(asset_version_name):
	asset_version = frappe.get_doc("Asset Version", asset_version_name)
	if not asset_version.file:
		frappe.throw(_("Asset Version {0} has no attached file.").format(asset_version.name))
	file_doc = frappe.get_doc("File", {"file_url": asset_version.file})
	path = Path(file_doc.get_full_path())
	if not path.exists():
		frappe.throw(_("Asset Version file does not exist: {0}").format(path))
	return path


def _escape_concat_path(path):
	return str(path).replace("'", "'\\''")
