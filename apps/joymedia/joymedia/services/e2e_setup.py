import os
import subprocess
import frappe
from frappe.utils import get_site_path

def _generate_video_bytes(duration_seconds: int = 2) -> bytes:
	output_path = get_site_path("private", "files", f"tmp_e2e_{frappe.generate_hash(length=8)}.mp4")
	os.makedirs(os.path.dirname(output_path), exist_ok=True)
	cmd = [
		"ffmpeg", "-y",
		"-f", "lavfi", "-i", f"color=c=blue:s=320x240:d={duration_seconds}:r=24",
		"-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
		"-c:v", "libx264", "-pix_fmt", "yuv420p",
		"-c:a", "aac", "-shortest",
		output_path,
	]
	subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	with open(output_path, "rb") as f:
		data = f.read()
	os.remove(output_path)
	return data

def setup_e2e_project():
	frappe.set_user("Administrator")
	project_name = "E2E-STUDIO-TEST-1"
	cleanup_e2e_project(project_name)

	org = frappe.db.get_value("Client Organization", {}, "name")
	if not org:
		org = frappe.get_doc({
			"doctype": "Client Organization",
			"organization_name": "E2E Test Org",
		}).insert(ignore_permissions=True).name

	campaign = frappe.get_doc({
		"doctype": "Campaign",
		"campaign_name": "E2E Test Campaign",
		"product_name": "E2E Headphones",
		"client_organization": org,
	}).insert(ignore_permissions=True)

	project = frappe.get_doc({
		"doctype": "Media Project",
		"project_name": "E2E Studio Project",
		"campaign": campaign.name,
		"client_organization": org,
		"status": "Generating",
	})
	project.name = project_name
	project.insert(ignore_permissions=True)

	# Asset
	asset = frappe.get_doc({
		"doctype": "Media Asset",
		"asset_name": "E2E Asset",
		"client_organization": org,
		"media_project": project.name,
		"media_type": "Video",
		"is_output": 1,
	}).insert(ignore_permissions=True)

	# Video File
	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": "e2e-clip.mp4",
		"content": _generate_video_bytes(4),
		"is_private": 0,
		"attached_to_doctype": "Media Asset",
		"attached_to_name": asset.name,
	}).insert(ignore_permissions=True)

	version = frappe.get_doc({
		"doctype": "Asset Version",
		"media_asset": asset.name,
		"file": file_doc.file_url,
		"source": "Generated",
		"duration_seconds": 4.0,
		"fps": 24,
	}).insert(ignore_permissions=True)

	# Spec v1
	spec_1 = frappe.get_doc({
		"doctype": "Media Specification",
		"media_project": project.name,
		"version_number": 1,
		"fps": 24,
		"total_duration_seconds": 8,
		"status": "Ready",
	}).insert(ignore_permissions=True)

	shot_1 = frappe.get_doc({
		"doctype": "Shot Specification",
		"media_specification": spec_1.name,
		"shot_number": 1,
		"subject_identity": "E2E Hero Shot 1",
		"action_plot": "Opening move",
		"planned_frame_count": 96,
		"duration_seconds": 4.0,
	}).insert(ignore_permissions=True)
	shot_1.db_set("selected_output_asset_version", version.name, update_modified=False)

	shot_2 = frappe.get_doc({
		"doctype": "Shot Specification",
		"media_specification": spec_1.name,
		"shot_number": 2,
		"subject_identity": "E2E Hero Shot 2",
		"action_plot": "Closing move",
		"planned_frame_count": 96,
		"duration_seconds": 4.0,
	}).insert(ignore_permissions=True)
	shot_2.db_set("selected_output_asset_version", version.name, update_modified=False)

	# Initialize timeline clips
	from joymedia.services.timeline_editor import get_project_timeline
	timeline = get_project_timeline(project.name)
	frappe.db.commit()

	return {
		"project_name": project.name,
		"spec_1": spec_1.name,
		"timeline": timeline,
	}

def create_spec_v2(project_name):
	frappe.set_user("Administrator")
	project = frappe.get_doc("Media Project", project_name)

	asset = frappe.db.get_value("Media Asset", {"media_project": project.name}, "name")
	if not asset:
		asset = frappe.get_doc({
			"doctype": "Media Asset",
			"asset_name": "E2E Asset V2",
			"client_organization": project.client_organization,
			"media_project": project.name,
			"media_type": "Video",
			"is_output": 1,
		}).insert(ignore_permissions=True).name
	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": "e2e-clip-v2.mp4",
		"content": _generate_video_bytes(4),
		"is_private": 0,
		"attached_to_doctype": "Media Asset",
		"attached_to_name": asset,
	}).insert(ignore_permissions=True)

	version_2 = frappe.get_doc({
		"doctype": "Asset Version",
		"media_asset": asset,
		"file": file_doc.file_url,
		"source": "Generated",
		"duration_seconds": 4.0,
		"fps": 24,
	}).insert(ignore_permissions=True)

	spec_2 = frappe.get_doc({
		"doctype": "Media Specification",
		"media_project": project.name,
		"version_number": 2,
		"fps": 24,
		"total_duration_seconds": 8,
		"status": "Ready",
	}).insert(ignore_permissions=True)

	shot_v2_1 = frappe.get_doc({
		"doctype": "Shot Specification",
		"media_specification": spec_2.name,
		"shot_number": 1,
		"subject_identity": "E2E Hero V2 Shot 1",
		"action_plot": "New v2 opening",
		"planned_frame_count": 96,
		"duration_seconds": 4.0,
	}).insert(ignore_permissions=True)
	shot_v2_1.db_set("selected_output_asset_version", version_2.name, update_modified=False)

	shot_v2_2 = frappe.get_doc({
		"doctype": "Shot Specification",
		"media_specification": spec_2.name,
		"shot_number": 2,
		"subject_identity": "E2E Hero V2 Shot 2",
		"action_plot": "New v2 closing",
		"planned_frame_count": 96,
		"duration_seconds": 4.0,
	}).insert(ignore_permissions=True)
	shot_v2_2.db_set("selected_output_asset_version", version_2.name, update_modified=False)

	frappe.db.commit()
	return spec_2.name

def cleanup_e2e_project(project_name="E2E-STUDIO-TEST-1"):
	frappe.set_user("Administrator")
	if not frappe.db.exists("Media Project", project_name):
		return
	frappe.db.delete("Timeline Clip", {"media_project": project_name})
	specs = frappe.get_all("Media Specification", filters={"media_project": project_name}, pluck="name")
	for s in specs:
		frappe.db.delete("Shot Specification", {"media_specification": s})
		frappe.db.delete("Media Specification", {"name": s})
	assets = frappe.get_all("Media Asset", filters={"media_project": project_name}, pluck="name")
	for a in assets:
		frappe.db.delete("Asset Version", {"media_asset": a})
		frappe.db.delete("Media Asset", {"name": a})
	campaign = frappe.db.get_value("Media Project", project_name, "campaign")
	frappe.db.delete("Media Project", {"name": project_name})
	if campaign:
		frappe.db.delete("Campaign", {"name": campaign})
	frappe.db.commit()
