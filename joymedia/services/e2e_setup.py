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
		"-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
		"-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", output_path,
	]
	subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	with open(output_path, "rb") as file_handle:
		data = file_handle.read()
	os.remove(output_path)
	return data


def _create_output_asset(project, name, file_name):
	asset = frappe.get_doc({
		"doctype": "Media Asset",
		"asset_name": name,
		"media_project": project.name,
		"media_type": "Video",
		"asset_category": "Other",
		"asset_scope": "Project Output",
	}).insert(ignore_permissions=True)
	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": file_name,
		"content": _generate_video_bytes(4),
		"is_private": 0,
		"attached_to_doctype": "Media Asset",
		"attached_to_name": asset.name,
	}).insert(ignore_permissions=True)
	return frappe.get_doc({
		"doctype": "Asset Version",
		"media_asset": asset.name,
		"file": file_doc.file_url,
		"source": "Generated",
	}).insert(ignore_permissions=True)


def _create_spec(project, version_number):
	return frappe.get_doc({
		"doctype": "Media Specification",
		"media_project": project.name,
		"version_number": version_number,
		"total_duration_seconds": 8,
		"delivery_preset": "Landscape",
		"continuity_mode": "Multi-shot",
		"status": "Ready",
	}).insert(ignore_permissions=True)


def _create_shot(specification, number, prompt, output_version):
	shot = frappe.get_doc({
		"doctype": "Shot Specification",
		"media_specification": specification.name,
		"shot_number": number,
		"shot_name": f"Shot {number}",
		"generation_prompt": prompt,
		"duration_seconds": 4.0,
	}).insert(ignore_permissions=True)
	shot.db_set("selected_output_asset_version", output_version.name, update_modified=False)
	return shot


def setup_e2e_project():
	frappe.set_user("Administrator")
	project_name = "E2E-STUDIO-TEST-1"
	cleanup_e2e_project(project_name)
	project = frappe.get_doc({
		"doctype": "Media Project",
		"project_name": "E2E Studio Project",
		"product_name": "E2E Headphones",
		"video_idea": "Create an E2E product showcase.",
		"status": "Draft",
	})
	project.name = project_name
	project.insert(ignore_permissions=True)
	version = _create_output_asset(project, "E2E Shot Output", "e2e-clip.mp4")
	specification = _create_spec(project, 1)
	_create_shot(specification, 1, "Opening hero product shot.", version)
	_create_shot(specification, 2, "Closing hero product shot.", version)
	from joymedia.services.timeline_editor import get_project_timeline
	timeline = get_project_timeline(project.name)
	frappe.db.commit()
	return {"project_name": project.name, "spec_1": specification.name, "timeline": timeline}


def create_spec_v2(project_name):
	frappe.set_user("Administrator")
	project = frappe.get_doc("Media Project", project_name)
	version = _create_output_asset(project, "E2E Shot Output V2", "e2e-clip-v2.mp4")
	specification = _create_spec(project, 2)
	_create_shot(specification, 1, "New version opening product shot.", version)
	_create_shot(specification, 2, "New version closing product shot.", version)
	frappe.db.commit()
	return specification.name


def cleanup_e2e_project(project_name="E2E-STUDIO-TEST-1"):
	frappe.set_user("Administrator")
	if not frappe.db.exists("Media Project", project_name):
		return
	frappe.db.delete("Timeline Clip", {"media_project": project_name})
	specifications = frappe.get_all("Media Specification", filters={"media_project": project_name}, pluck="name")
	for specification in specifications:
		frappe.db.delete("Shot Specification", {"media_specification": specification})
		frappe.db.delete("Media Specification", {"name": specification})
	assets = frappe.get_all("Media Asset", filters={"media_project": project_name}, pluck="name")
	for asset in assets:
		frappe.db.delete("Asset Version", {"media_asset": asset})
		frappe.db.delete("Media Asset", {"name": asset})
	frappe.db.delete("Media Project", {"name": project_name})
	frappe.db.commit()
