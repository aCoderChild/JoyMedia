"""Automatic source-pixel preparation through a frozen provider recipe.

No case names, model inference implementations, or client-authored coordinates.
Ambiguous placement fails before the frame can be approved or animated.
"""

import hashlib
import io
import json
import re
import time
from pathlib import Path

import frappe
from frappe.utils.synchronization import filelock

from joymedia.services.workflows import comfyui


class RetentionRejected(ValueError):
	"""Prepared output is unusable; never retry it as a transient GPU error."""


def rejection_reason(diagnostic):
	"""Keep the worker's final cause ahead of warning/traceback noise."""
	causes = re.findall(r"^(?:[\w.]+Error|[\w.]+Exception):\s*(.+)$", str(diagnostic or ""), re.MULTILINE)
	if causes:
		return causes[-1].strip()[:350]
	lines = [line.strip() for line in str(diagnostic or "").splitlines() if line.strip()]
	return (lines[-1] if lines else "No preparation diagnostic was returned.")[:350]


def policy():
	value = frappe.conf.get("joymedia_reference_retention") or {}
	if not isinstance(value, dict):
		raise ValueError("Reference retention settings must be an object.")
	if not value.get("enabled"):
		return None
	recipe = value.get("recipe_sha256")
	if not isinstance(recipe, str) or len(recipe) != 64 or any(c not in "0123456789abcdef" for c in recipe):
		raise ValueError("Reference retention needs a pinned preparation recipe.")
	workflow = frappe.get_doc("Generation Workflow", value.get("workflow"))
	result = {
		"version": 1,
		"recipe_sha256": recipe,
		"required_roles": ["product"],
		"workflow": workflow.name,
		"workflow_hash": workflow.workflow_hash,
	}
	if value.get("source_hold_pipeline") and value.get("source_hold_workflow"):
		result.update(
			source_hold_pipeline=value["source_hold_pipeline"],
			source_hold_workflow=value["source_hold_workflow"],
		)
	return result


def required_sources(references):
	return list(
		dict.fromkeys(
			r["asset_version"]
			for r in references or []
			if str(r.get("reference_role") or r.get("input_role") or "").lower() == "product"
			and r.get("asset_version")
			and r.get("preservation_mode", "source_pixels") != "reference_guided"
		)
	)


def _write_json(path, value):
	temporary = path.with_suffix(".tmp")
	temporary.write_text(json.dumps(value, sort_keys=True))
	temporary.replace(path)


def validate_prepared(image_bytes, patch_bytes, report, source_hash, frozen):
	from PIL import Image

	if (
		report.get("source_sha256") != source_hash
		or report.get("recipe_sha256") != frozen["recipe_sha256"]
		or report.get("source_rgb_unchanged") is not True
	):
		raise ValueError("Prepared source evidence does not match the frozen reference recipe.")
	box = report.get("box")
	if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
		raise ValueError("Prepared reference has invalid placement evidence.")
	x, y, w, h = box
	with Image.open(io.BytesIO(image_bytes)) as canvas, Image.open(io.BytesIO(patch_bytes)) as patch:
		if (
			x < 0
			or y < 0
			or w < 1
			or h < 1
			or x + w > canvas.width
			or y + h > canvas.height
			or patch.size != (w, h)
		):
			raise ValueError("Prepared reference is outside its canvas or changed shape.")
		visible = patch.convert("RGBA")
		if not any(v >= 254 for v in visible.getchannel("A").getdata()):
			raise ValueError("Prepared reference has no opaque source evidence.")
		region = canvas.convert("RGB").crop((x, y, x + w, y + h))
		for actual, expected, alpha in zip(
			region.getdata(),
			visible.convert("RGB").getdata(),
			visible.getchannel("A").getdata(),
			strict=False,
		):
			if alpha >= 254 and max(abs(a - b) for a, b in zip(actual, expected, strict=False)) > 2:
				raise ValueError("Prepared source pixels do not match the declared placement.")


def retain(attempt, image_bytes, references, frozen, lock):
	"""Detect staging, prepare alpha, insert original artwork and retain evidence."""
	from PIL import Image

	base = attempt.comfyui_endpoint_url
	for version in required_sources(references):
		source = frappe.get_doc("Asset Version", version)
		file = frappe.get_doc("File", {"file_url": source.file})
		content = Path(file.get_full_path()).read_bytes()
		if hashlib.sha256(content).hexdigest() != source.content_hash:
			raise ValueError("The immutable reference file changed.")
		key = hashlib.sha256(image_bytes + content + json.dumps(frozen, sort_keys=True).encode()).hexdigest()
		folder = Path(frappe.get_site_path("private", "joymedia-retention", key))
		folder.mkdir(parents=True, exist_ok=True)
		with filelock(f"joymedia-retention-{key}"):
			if (folder / "evidence.json").exists() and (folder / "result.png").exists():
				report = json.loads((folder / "evidence.json").read_text())
				image_bytes = (folder / "result.png").read_bytes()
				patch = (folder / "patch.png").read_bytes()
				if (
					report.get("result_sha256") != hashlib.sha256(image_bytes).hexdigest()
					or report.get("patch_sha256") != hashlib.sha256(patch).hexdigest()
				):
					raise ValueError("Prepared reference cache changed; do not accept altered artwork.")
			else:
				job_path = folder / "job.json"
				if job_path.exists():
					job = json.loads(job_path.read_text())
					if job["endpoint"] != base:
						raise ValueError("A reference preparation belongs to a different frozen endpoint.")
				else:
					path = folder / "scene.png"
					path.write_bytes(image_bytes)
					scene = comfyui.upload_local_file(path, base_url=base)
					upload = comfyui.upload_local_file(file.get_full_path(), base_url=base)
					from joymedia.services.workflows.resolver import build_execution_workflow

					workflow = frappe.get_doc("Generation Workflow", frozen["workflow"])
					if workflow.workflow_hash != frozen["workflow_hash"]:
						raise ValueError("Reference workflow differs from the frozen recipe.")
					graph = build_execution_workflow(
						workflow,
						inputs={
							"scene": scene["server_path"],
							"source": upload["server_path"],
							"recipe": frozen["recipe_sha256"],
						},
						seed=0,
						width=1,
						height=1,
						fps=1,
						frame_count=1,
						output_prefix=key,
					)
					submitted = comfyui.submit_workflow(graph, base_url=base, client_id=key)
					job = {"prompt_id": submitted["prompt_id"], "endpoint": base}
					_write_json(job_path, job)
				deadline = time.monotonic() + 600
				while time.monotonic() < deadline:
					history = comfyui.get_history(job["prompt_id"], base_url=base).get(job["prompt_id"], {})
					if history.get("status", {}).get("status_str") == "error":
						diagnostic = next(
							(
								data.get("exception_message", "")
								for name, data in history.get("status", {}).get("messages", [])
								if name == "execution_error"
							),
							"",
						)
						raise RetentionRejected(
							"Reference preparation was rejected. No unprotected frame was accepted. "
							+ rejection_reason(diagnostic)
						)
					output = history.get("outputs", {}).get(
						frappe.db.get_value(
							"Generation Workflow", frozen["workflow"], "primary_output_node_key"
						)
					)
					if output:
						break
					time.sleep(1)
				else:
					raise ValueError(
						"Reference preparation is still pending. Its existing job can be resumed."
					)
				images, reports = output.get("images", []), output.get("retention", [])
				if (
					len(images) != 2
					or len(reports) != 1
					or reports[0].get("source_sha256") != source.content_hash
					or not reports[0].get("source_rgb_unchanged")
					or reports[0].get("recipe_sha256") != frozen["recipe_sha256"]
				):
					raise ValueError("Reference preparation returned incomplete source evidence.")

				def download(item):
					return comfyui.download_output(
						item["filename"], item.get("subfolder", ""), item.get("type", "output"), base_url=base
					)

				image_bytes, patch = download(images[0]), download(images[1])
				report = {
					**reports[0],
					"source_asset_version": version,
					"preparation_prompt_id": job["prompt_id"],
				}
				(folder / "result.png").write_bytes(image_bytes)
				(folder / "patch.png").write_bytes(patch)
				report["result_sha256"] = hashlib.sha256(image_bytes).hexdigest()
				report["patch_sha256"] = hashlib.sha256(patch).hexdigest()
				_write_json(folder / "evidence.json", report)
			validate_prepared(image_bytes, patch, report, source.content_hash, frozen)
			with Image.open(io.BytesIO(image_bytes)) as image:
				lock["canvas"] = list(image.size)
			lock.setdefault("items", []).append(
				{"box": report["box"], "png": patch, "source_asset_version": version}
			)
			lock.setdefault("provenance", []).append(report)
	return image_bytes


def require_coverage(shot_snapshot, lock):
	"""A product-bearing scene cannot silently graduate without source artwork."""
	if not shot_snapshot.get("reference_retention"):
		return
	needed = set(required_sources(shot_snapshot.get("references")))
	covered = {
		item.get("source_asset_version")
		for item in (lock or {}).get("items", [])
		if item.get("coordinate_space", "world") == "world"
	}
	if needed - covered:
		raise ValueError("This scene has no complete source-art protection for its product references.")


def needs_identity_review(scene):
	"""Unverified deforming identities never become automatically accepted takes."""
	if any(
		str(r.get("reference_role") or "").lower() == "product"
		and r.get("preservation_mode") == "reference_guided"
		for r in scene.get("references", [])
	):
		return True
	if not scene.get("reference_retention"):
		return False
	has_actor = any(
		str(r.get("reference_role") or "").lower() in {"character", "person"}
		for r in scene.get("references", [])
	)
	# This declared mode is rendered entirely from its frozen source image.
	full_hold = float(scene.get("closing_hold_seconds") or 0) >= float(
		scene.get("duration_seconds") or float(scene.get("planned_frame_count") or 0) / 24 or 1
	)
	return has_actor and not full_hold


def needs_candidate_review(scene):
	"""Source fidelity does not establish physical placement in a generated scene."""
	from joymedia.services.review.admission import requires_geometry_review

	if scene.get("visual_admission_required") and requires_geometry_review(scene):
		return True
	if (
		scene.get("visual_admission_required")
		and scene.get("render_strategy") == "controlled_source_presentation"
		and is_static_presentation(scene)
		and any(
			str(r.get("reference_role") or "").lower() == "first_frame" and r.get("asset_version")
			for r in scene.get("references", [])
		)
	):
		# The exact source condition is already selected, the renderer introduces
		# no subject motion, and admission/source coverage still run before promotion.
		return False
	if needs_identity_review(scene):
		return True
	if not scene.get("reference_retention") or not required_sources(scene.get("references")):
		return False
	duration = float(scene.get("duration_seconds") or float(scene.get("planned_frame_count") or 0) / 24 or 1)
	return float(scene.get("closing_hold_seconds") or 0) < duration


def allows_automatic_finishing(run):
	scope = frappe.parse_json(run.execution_scope_json or "{}") or {}
	snapshot = frappe.parse_json(run.project_snapshot_json or "{}") or {}
	names = set(scope.get("shot_names") or [])
	return not scope.get("candidate_only") and not any(
		needs_candidate_review(row)
		for row in snapshot.get("shots", [])
		if not names or row.get("shot") in names
	)


def authored_static_product_hold(scene):
	"""Recognise the application's literal stationary product action, not a motion label."""
	references = scene.get("references") or []
	roles = {str(r.get("reference_role") or "").lower() for r in references}
	if roles & {"character", "person", "people", "talent"} or not required_sources(references):
		return False
	from joymedia.services.scene.prompt_scope import assert_product_only_direction

	try:
		assert_product_only_direction(
			"\n".join(str(scene.get(k) or "") for k in ("generation_prompt", "start_state", "end_state"))
		)
	except ValueError:
		return False
	plan = scene.get("motion_plan_json") or {}
	plan = json.loads(plan) if isinstance(plan, str) else plan
	actions = plan.get("actions") or []
	return bool(actions) and all(
		re.fullmatch(
			r"The original product (?:remains|stays) in its (?:established|opening) position "
			r"(?:with its printed artwork intact|with unchanged visible artwork and support)\.?",
			str(row.get("action") or "").strip(),
			re.I,
		)
		for row in actions
	)


def is_static_presentation(scene):
	"""Use exact source frames only when the plan explicitly forbids subject/camera motion."""
	from joymedia.services.scene.contract import read_contract

	references = scene.get("references") or []
	has_actor = any(str(r.get("reference_role") or "").lower() in {"character", "person"} for r in references)
	explicit = [
		r
		for r in references
		if str(r.get("reference_role") or "").lower() == "first_frame" and r.get("asset_version")
	]
	# A static actor presentation is safe only with an explicitly authored
	# source frame. Reference conditioning alone never authorizes freezing it.
	if has_actor and len(explicit) != 1:
		return False
	if not required_sources(references) and not (has_actor and len(explicit) == 1):
		return False
	plan = scene.get("motion_plan_json") or {}
	plan = json.loads(plan) if isinstance(plan, str) else plan
	contract = read_contract(plan, scene.get("duration_seconds"))
	if scene.get("effective_camera_behavior") == "locked" and authored_static_product_hold(scene):
		return True
	if not contract or contract.get("events") or plan.get("camera_motion") != "locked":
		return False
	motion = {
		row["entity"]: str(row["value"]).strip().lower()
		for row in contract.get("properties", [])
		if row["name"] == "motion"
	}
	return bool(contract["entities"]) and all(
		motion.get(row["id"]) == "stationary" for row in contract["entities"]
	)


def route_presentation(scene, frozen):
	if not frozen or not frozen.get("source_hold_pipeline") or not is_static_presentation(scene):
		return
	pipeline = frappe.get_doc("Generation Pipeline", frozen["source_hold_pipeline"])
	workflow = frappe.get_doc("Generation Workflow", frozen["source_hold_workflow"])
	from joymedia.services.workflows.capabilities import controls

	if (
		"source_frame_hold" not in controls(workflow)
		or not pipeline.steps
		or pipeline.steps[-1].workflow != workflow.name
	):
		raise ValueError("The source presentation route is not a declared source-frame workflow.")
	scene.update(
		workflow=workflow.name,
		generation_pipeline=pipeline.name,
		render_strategy="controlled_source_presentation",
		routing_reason="Locked product and camera; preserve the original source frame.",
		requires_recomposition=True,
	)
