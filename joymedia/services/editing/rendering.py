"""Execute existing finishing workflows and persist their immutable media outputs."""

import hashlib
import math
import re
import subprocess
from pathlib import Path

import frappe
from frappe import _

COMFYUI_JOB_TIMEOUT_SECONDS = 3600


def _video_workflow(project_name, first_frame, prompt, seconds, last_frame=None, size=None):
	"""Build a post-production prompt solely from the selected workflow contract.

	An optional ``last_frame`` is sent only to workflows that explicitly declare
	it.  This makes transition quality a workflow capability, not a backend
	branch tied to a provider, node id, or model name.
	"""
	from joymedia.services.workflows.comfyui import upload_local_file
	from joymedia.services.workflows.resolver import build_execution_workflow, get_workflow_input_contract
	from joymedia.workflow_adapters import get_workflow_adapter

	project = frappe.get_doc("Media Project", project_name)
	if not project.workflow:
		frappe.throw(_("Select a video generation workflow before finishing the film."))
	workflow_version = frappe.get_doc("Generation Workflow", project.workflow)
	contract = {item["role"]: item for item in get_workflow_input_contract(workflow_version)}
	if "first_frame" not in contract and workflow_version.continuation_workflow:
		workflow_version = frappe.get_doc("Generation Workflow", workflow_version.continuation_workflow)
		contract = {item["role"]: item for item in get_workflow_input_contract(workflow_version)}
	if workflow_version.output_media_type != "Video" or "first_frame" not in contract:
		frappe.throw(_("The selected workflow cannot render video from a first frame."))
	inputs = {
		"generation_prompt": prompt,
		"first_frame": upload_local_file(first_frame)["server_path"],
	}
	if last_frame and "last_frame" in contract:
		inputs["last_frame"] = upload_local_file(last_frame)["server_path"]
	from joymedia.services.project.formats import require_dimensions

	width, height = require_dimensions(project)
	fps = float(workflow_version.output_fps or 0)
	if fps <= 0:
		raise ValueError("The finishing workflow must declare output FPS.")
	frame_count = max(1, math.ceil(float(seconds) * fps))
	seed_material = f"{project_name}|{prompt}|{frame_count}|{first_frame}|{last_frame or ''}"
	workflow = build_execution_workflow(
		workflow_version,
		inputs=inputs,
		seed=int(hashlib.sha256(seed_material.encode()).hexdigest()[:12], 16),
		width=int(size[0] if size else width),
		height=int(size[1] if size else height),
		fps=fps,
		frame_count=frame_count,
		output_prefix=f"joymedia/post/{frappe.generate_hash(length=10)}",
	)
	metadata = get_workflow_adapter(workflow_version).extract_execution_metadata(workflow)
	return workflow, metadata["primary_output_node_key"]


def _render_video(project_name, workflow, output_node):
	from joymedia.services.workflows.comfyui import run_workflow_to_bytes

	def remember_prompt(prompt_id):
		frappe.db.set_value(
			"Media Project", project_name, "post_production_comfy_prompt_id", prompt_id, update_modified=False
		)
		frappe.db.commit()

	content = run_workflow_to_bytes(
		workflow, output_node, timeout=COMFYUI_JOB_TIMEOUT_SECONDS, forget=True, on_submitted=remember_prompt
	)
	# The render took minutes; MariaDB's snapshot isolation rejects writes to rows
	# (such as naming series) that other workers changed since this transaction began.
	frappe.db.commit()
	return content


def _extract_frame(video_path, frame_index, output_path):
	subprocess.run(
		[
			"ffmpeg",
			"-v",
			"error",
			"-y",
			"-i",
			str(video_path),
			"-vf",
			f"select='eq(n,{max(0, frame_index)})'",
			"-frames:v",
			"1",
			"-update",
			"1",
			str(output_path),
		],
		check=True,
		capture_output=True,
		timeout=120,
	)
	if not Path(output_path).exists():
		raise ValueError(_("Frame {0} is outside {1}.").format(frame_index, Path(video_path).name))


def _save_output(project_name, asset_name, media_type, file_name, content):
	asset = frappe.db.get_value(
		"Media Asset", {"asset_name": asset_name, "media_project": project_name}, "name"
	)
	if not asset:
		asset = (
			frappe.get_doc(
				{
					"doctype": "Media Asset",
					"asset_name": asset_name,
					"media_project": project_name,
					"media_type": media_type,
					"asset_category": "Other",
					"asset_scope": "Project Output",
					"status": "Active",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": asset,
		}
	).insert(ignore_permissions=True)
	version = frappe.get_doc(
		{"doctype": "Asset Version", "media_asset": asset, "file": file_doc.file_url, "source": "Generated"}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return version.name


def _slug(text):
	return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:120]
