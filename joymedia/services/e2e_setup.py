import os
import subprocess
from math import ceil

import frappe
from frappe.utils import get_site_path


def _generate_video_bytes(duration_seconds: int = 2, color: str = "blue", unique_tag: str = "") -> bytes:
	output_path = get_site_path("private", "files", f"tmp_e2e_{frappe.generate_hash(length=8)}.mp4")
	os.makedirs(os.path.dirname(output_path), exist_ok=True)
	cmd = [
		"ffmpeg", "-y",
		"-f", "lavfi", "-i", f"color=c={color}:s=320x240:d={duration_seconds}:r=24",
		"-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
		"-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", output_path,
	]
	if unique_tag:
		cmd[-1:-1] = ["-metadata", f"comment={unique_tag}"]
	subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	with open(output_path, "rb") as file_handle:
		data = file_handle.read()
	os.remove(output_path)
	return data


def _generate_image_bytes() -> bytes:
	import io
	from PIL import Image
	img = Image.new("RGB", (320, 240), color=(200, 50, 80))
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


def _create_output_asset(project, name, file_name, duration_seconds: int = 4, color: str = "blue"):
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
		"file_name": f"{project.name}-{file_name}",
		"content": _generate_video_bytes(duration_seconds, color=color, unique_tag=project.name),
		"is_private": 1,
		"attached_to_doctype": "Media Asset",
		"attached_to_name": asset.name,
	}).insert(ignore_permissions=True)
	return frappe.get_doc({
		"doctype": "Asset Version",
		"media_asset": asset.name,
		"file": file_doc.file_url,
		"source": "Generated",
	}).insert(ignore_permissions=True)


def _configure_project(project, total_duration_seconds=8):
	workflow = frappe.db.get_value("Generation Workflow", {}, "name", order_by="creation desc")
	if not workflow:
		frappe.throw("An executable Generation Workflow is required for the E2E setup.")
	project.total_duration_seconds = total_duration_seconds
	project.delivery_preset = "Landscape"
	project.delivery_width = 1920
	project.delivery_height = 1080
	project.generation_mode = "Multi-shot"
	project.workflow = workflow
	project.save(ignore_permissions=True)
	return project


def _create_shot(project, number, prompt, output_version, duration_seconds=4.0):
	shot = frappe.get_doc({
		"doctype": "Shot",
		"media_project": project.name,
		"shot_number": number,
		"shot_name": f"Shot {number}",
		"generation_prompt": prompt,
		"duration_seconds": duration_seconds,
	}).insert(ignore_permissions=True)
	shot.db_set("selected_output_asset_version", output_version.name, update_modified=False)
	return shot


def setup_e2e_project(project_name="E2E-STUDIO-TEST-1", duration_seconds=8):
	frappe.set_user("Administrator")
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
	_configure_project(project, total_duration_seconds=duration_seconds)
	shot_duration = float(duration_seconds) / 2
	version = _create_output_asset(
		project, "E2E Shot Output", "e2e-clip.mp4", duration_seconds=max(1, ceil(shot_duration))
	)
	_create_shot(project, 1, "Opening hero product shot.", version, duration_seconds=shot_duration)
	_create_shot(project, 2, "Closing hero product shot.", version, duration_seconds=shot_duration)
	final_version = _create_output_asset(
		project, "E2E Final Master Output", "e2e-final.mp4", duration_seconds=duration_seconds, color="green"
	)
	# This fixture represents a project that has already been explicitly exported.
	# Generation Run itself owns only generation state; delivery stays on Media Project.
	project.current_output_asset_version = final_version.name
	project.save(ignore_permissions=True)
	audio_asset = frappe.get_doc({
		"doctype": "Media Asset",
		"asset_name": "Upbeat Cinematic Music",
		"media_type": "Audio",
		"asset_category": "Audio",
		"asset_scope": "Library",
	}).insert(ignore_permissions=True)
	audio_file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": "bgm.mp3",
		"content": _generate_video_bytes(2),
		"is_private": 0,
		"attached_to_doctype": "Media Asset",
		"attached_to_name": audio_asset.name,
	}).insert(ignore_permissions=True)
	audio_version = frappe.get_doc({
		"doctype": "Asset Version",
		"media_asset": audio_asset.name,
		"file": audio_file_doc.file_url,
		"source": "Uploaded",
		"duration_seconds": 15.0,
	}).insert(ignore_permissions=True)
	from joymedia.api.assets import select_project_reference
	select_project_reference(project.name, audio_asset.name, reference_role="Audio")
	from joymedia.services.project_context import build_project_snapshot
	project_snapshot_json, project_snapshot_hash = build_project_snapshot(project)
	frappe.get_doc({
		"doctype": "Generation Run",
		"media_project": project.name,
		"project_snapshot_json": project_snapshot_json,
		"project_snapshot_hash": project_snapshot_hash,
		"workflow": project.workflow,
		"requested_by": "Administrator",
		"status": "Completed",
	}).insert(ignore_permissions=True)
	from joymedia.services.timeline_editor import get_project_timeline, add_timeline_audio_clip
	get_project_timeline(project.name)
	timeline = add_timeline_audio_clip(project.name, audio_version.name, timeline_start_frame=0, audio_role="BGM")
	project.db_set("current_output_asset_version", final_version.name, update_modified=False)
	frappe.db.commit()
	return {"project_name": project.name, "timeline": timeline}


def setup_fresh_empty_project(project_name="E2E-FRESH-EMPTY-1"):
	frappe.set_user("Administrator")
	cleanup_e2e_project(project_name)
	project = frappe.get_doc({
		"doctype": "Media Project",
		"project_name": "Fresh Lipstick Project",
		"product_name": "Luxury Lipstick",
		"video_idea": "",
		"status": "Draft",
	})
	project.name = project_name
	project.insert(ignore_permissions=True)
	_configure_project(project)
	img_asset = frappe.get_doc({
		"doctype": "Media Asset",
		"asset_name": "Lipstick Product Photo",
		"media_type": "Image",
		"asset_category": "Product",
		"asset_scope": "Library",
	}).insert(ignore_permissions=True)
	img_file = frappe.get_doc({
		"doctype": "File",
		"file_name": "lipstick.png",
		"content": _generate_image_bytes(),
		"is_private": 0,
		"attached_to_doctype": "Media Asset",
		"attached_to_name": img_asset.name,
	}).insert(ignore_permissions=True)
	frappe.get_doc({
		"doctype": "Asset Version",
		"media_asset": img_asset.name,
		"file": img_file.file_url,
		"source": "Uploaded",
	}).insert(ignore_permissions=True)
	from joymedia.api.assets import select_project_reference
	select_project_reference(project.name, img_asset.name, reference_role="Product")
	frappe.db.commit()
	return {"project_name": project.name}


def setup_live_comfy_queue_project(
	project_name,
	product_image_path,
	people_image_path,
	environment_image_path,
	workflow="WF-02624",
	pipeline="PIPE-00016",
):
	"""Create an isolated two-shot fixture for real ComfyUI queue testing.

	Shot 1 exercises a composed product/people/environment reference board;
	Shot 2 intentionally has no references to exercise the text-to-image branch.
	This helper never deletes existing records and rejects a reused project name.
	"""
	frappe.set_user("Administrator")
	if frappe.db.exists("Media Project", project_name):
		frappe.throw(f"Refusing to overwrite existing live test project {project_name}.")
	for path in (product_image_path, people_image_path, environment_image_path):
		if not os.path.isfile(path):
			frappe.throw(f"Live ComfyUI test image does not exist: {path}")

	project = frappe.get_doc({
		"doctype": "Media Project",
		"project_name": f"Live ComfyUI Queue Test {project_name}",
		"product_name": "SAN PHAM AI reference-composition test",
		"video_idea": "Show the referenced product with the supplied person and environment; make a clean text-only product scene in the second shot.",
		"total_duration_seconds": 10,
		"delivery_preset": "Landscape",
		"delivery_width": 1920,
		"delivery_height": 1080,
		"generation_mode": "Multi-shot",
		"quality_mode": "Draft",
		"reference_mode": "Multi-reference",
		"workflow": workflow,
		"generation_pipeline": pipeline,
		"status": "Draft",
	})
	project.name = project_name
	project.insert(ignore_permissions=True)

	def add_reference(label, role, path):
		asset = frappe.get_doc({
			"doctype": "Media Asset",
			"asset_name": f"{project_name} {label}",
			"media_type": "Image",
			"asset_category": {"Product": "Product", "Character": "Character", "Environment": "Background"}[role],
			"asset_scope": "Library",
		}).insert(ignore_permissions=True)
		with open(path, "rb") as image_file:
			file_doc = frappe.get_doc({
				"doctype": "File",
				"file_name": os.path.basename(path),
				"content": image_file.read(),
				"is_private": 1,
				"attached_to_doctype": "Media Asset",
				"attached_to_name": asset.name,
			}).insert(ignore_permissions=True)
		version = frappe.get_doc({
			"doctype": "Asset Version",
			"media_asset": asset.name,
			"file": file_doc.file_url,
			"source": "Uploaded",
		}).insert(ignore_permissions=True)
		project.append("selected_media", {
			"reference_key": frappe.scrub(label),
			"asset_version": version.name,
			"reference_role": role,
			"label": label,
		})
		return version.name

	product = add_reference("Product", "Product", product_image_path)
	person = add_reference("Person", "Character", people_image_path)
	environment = add_reference("Environment", "Environment", environment_image_path)
	project.save(ignore_permissions=True)

	for number, prompt in (
		(1, "A five-second polished product advertisement. Show the lipstick clearly in the hands of the referenced woman, inside the referenced luxury hotel environment. Natural movement, premium commercial lighting, product remains recognizable."),
		(2, "A five-second premium lipstick commercial in a warm, elegant setting. Slow camera push toward the lipstick on a marble vanity, soft practical lighting, realistic reflections, no people or text."),
	):
		shot = frappe.get_doc({
			"doctype": "Shot",
			"media_project": project.name,
			"shot_number": number,
			"shot_name": "Reference composition" if number == 1 else "No-reference generation",
			"generation_prompt": prompt,
			"duration_seconds": 5,
		}).insert(ignore_permissions=True)
		if number == 1:
			for role, version in (("Product", product), ("Character", person), ("Environment", environment)):
				shot.append("generation_inputs", {"reference_role": role, "asset_version": version})
			shot.save(ignore_permissions=True)

	frappe.db.commit()
	return {"project_name": project.name, "workflow": workflow, "pipeline": pipeline}


def create_project_revision_v2(project_name):
	frappe.set_user("Administrator")
	project = frappe.get_doc("Media Project", project_name)
	version = _create_output_asset(project, "E2E Shot Output V2", "e2e-clip-v2.mp4")
	_create_shot(project, 1, "New version opening product shot.", version)
	_create_shot(project, 2, "New version closing product shot.", version)
	frappe.db.commit()
	return project.name


def cleanup_e2e_project(project_name="E2E-STUDIO-TEST-1"):
	frappe.set_user("Administrator")
	if not frappe.db.exists("Media Project", project_name):
		return
	frappe.db.delete("Generation Run", {"media_project": project_name})
	frappe.db.delete("Timeline Clip", {"media_project": project_name})
	frappe.db.delete("Shot", {"media_project": project_name})
	assets = frappe.get_all("Media Asset", filters={"media_project": project_name}, pluck="name")
	for asset in assets:
		frappe.db.delete("Asset Version", {"media_asset": asset})
		frappe.db.delete("Media Asset", {"name": asset})
	frappe.db.delete("Media Project", {"name": project_name})
	frappe.db.commit()
