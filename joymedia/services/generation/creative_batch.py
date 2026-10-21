"""Durable orchestration over the existing workbook, generation and finishing jobs.

Batch completion means a review export. Existing identity, physical evidence,
candidate selection and release gates are never silently overridden.
"""

import copy

import frappe

from joymedia.services.project.render_queue import is_render_alive
from joymedia.services.workflows.pipeline import persist_execution_pin, pinned_execution


def _write(batch, variants, status=None, error="", changed_index=None):
	# Merge only the changed variant so planning and native render polling cannot
	# overwrite one another. Inference runs outside this short admission lock.
	with frappe.cache.lock(f"joymedia-creative:{batch}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		current = frappe.get_doc("Creative Batch", batch)
		if current.status == "Cancelled":
			return False
		if changed_index is not None:
			latest = frappe.parse_json(current.variants_json)
			latest[changed_index] = variants[changed_index]
			variants = latest
		states = {v["status"] for v in variants}
		if status is None:
			status = (
				"Completed"
				if states == {"Completed"}
				else "Scripts Ready"
				if states == {"Script Ready"}
				else "Planning"
				if states & {"Queued", "Planning"}
				else "Rendering"
				if states & {"Locations", "Keyframes", "Rendering"}
				else "Finishing"
				if states & {"Finishing", "Exporting"}
				else "Needs Attention"
			)
		frappe.db.set_value(
			"Creative Batch",
			{"name": batch, "status": ["!=", "Cancelled"]},
			{
				"variants_json": frappe.as_json(variants),
				"status": status,
				"error": error,
			},
			update_modified=True,
		)
		frappe.db.commit()
		return True


def _queue_prepare(batch_name, variants):
	index = next((i for i, v in enumerate(variants) if v["status"] in {"Queued", "Planning"}), None)
	if index is None:
		return
	job_id = f"joymedia-creative-prepare:{batch_name}:{index}"
	if not is_render_alive(job_id):
		frappe.enqueue(
			"joymedia.services.generation.creative_batch.prepare_batch",
			queue="long",
			timeout=3600,
			batch_name=batch_name,
			job_id=job_id,
			deduplicate=True,
			enqueue_after_commit=True,
		)


def _create_variant(batch, request, index):
	from joymedia.api.projects import create_project
	from joymedia.services.project.versions import copy_control_reference, family, organize_edits

	source = frappe.get_doc("Media Project", batch.source_project)
	root = family(source)
	project = create_project(f"{source.project_name} · {index + 1}", request["product_name"])
	project.workflow, project.generation_pipeline = request["workflow"], request["generation_pipeline"]
	for key, value in request.get("render_profile", {}).items():
		if value is not None:
			project.set(key, value)
	project.planning_mode, project.generation_mode = "Follow the sheet", "Multi-shot"
	project.total_duration_seconds = request.get("duration_seconds")
	project.delivery_width, project.delivery_height = request.get("width"), request.get("height")
	project.delivery_preset = request.get("delivery_preset")
	project.video_idea = request.get("direction") or ""
	project.storyboard_source_json = frappe.as_json({"brand": request["brand"]})
	project.soundtrack_mode = "Effects + music"
	reference_map = {}
	sheet_references = []
	for row in request["references"]:
		ref = copy.deepcopy(row)
		ref["asset_version"] = copy_control_reference(ref["asset_version"], source, project, reference_map)
		project.append("selected_media", ref)
		mode = request.get("reference_preservation_modes", {}).get(row["asset_version"])
		if mode:
			asset = frappe.get_doc("Asset Version", ref["asset_version"])
			sheet_references.append(
				{
					"name": ref["reference_key"],
					"file": frappe.get_doc("File", {"file_url": asset.file}).file_name,
					"role": ref["reference_role"],
					"preservation_mode": mode,
				}
			)
	project.storyboard_source_json = frappe.as_json(
		{"brand": request["brand"], "references": sheet_references}
	)
	project.save(ignore_permissions=True)
	organize_edits(
		root.name,
		[{"project": project.name, "label": f"AI {batch.name} · {index + 1}", "kind": "Experiment"}],
	)
	frappe.db.commit()
	persist_execution_pin(project.name, request["generation_pipeline"])
	return project


def prepare_batch(batch_name):
	"""Background CPU planning. Inference never holds a database or Redis lock."""
	from frappe.utils.file_manager import save_file

	from joymedia.api.storyboard import _plan_project, import_storyboard_workbook
	from joymedia.services.intake.action_reference import ensure_action_analysis
	from joymedia.services.intake.cinematography import ensure_project_camera_analysis
	from joymedia.services.planning.creative import draft_script, reference_inventory, script_workbook

	batch = frappe.get_doc("Creative Batch", batch_name)
	if batch.status == "Cancelled":
		return
	frappe.set_user(batch.owner)
	request = frappe.parse_json(batch.request_json)
	variants = frappe.parse_json(batch.variants_json)
	for index, variant in enumerate(variants):
		if variant["status"] not in {"Queued", "Planning"}:
			continue
		if not _write(batch.name, variants, "Planning", changed_index=index):
			return
		try:
			project = (
				frappe.get_doc("Media Project", variant["project"])
				if variant.get("project")
				else _create_variant(batch, request, index)
			)
			variant.update(project=project.name, status="Planning")
			if not _write(batch.name, variants, "Planning", changed_index=index):
				return
			ensure_project_camera_analysis(project)
			ensure_action_analysis(project)
			reference_inventory(project)
			frappe.db.commit()
			if not variant.get("script"):
				script = draft_script(
					project,
					nonce=variant["nonce"],
					review_notes=request.get("review_notes", []),
					previous=[v["script"]["logline"] for v in variants[:index] if v.get("script")],
				)
				if any(
					v.get("script", {}).get("logline", "").casefold() == script["logline"].casefold()
					for v in variants[:index]
				):
					raise ValueError("The proposed variant repeats an earlier concept.")
				variant["script"] = script
				if not _write(batch.name, variants, "Planning", changed_index=index):
					return
			script = variant["script"]
			if not variant.get("workbook"):
				file = save_file(
					f"{batch.name}-variant-{index + 1}.xlsx",
					script_workbook(script, project),
					"Media Project",
					project.name,
					is_private=1,
				)
				with pinned_execution(project.name, request["generation_pipeline"]):
					import_storyboard_workbook(project.name, file.name, "Storyboard")
				project.reload()
				project.soundtrack_prompt = script["music"]
				project.save(ignore_permissions=True)
				variant.update(workbook=file.file_url, title=script["title"])
				if not _write(batch.name, variants, "Planning", changed_index=index):
					return
			# Normal timed-sheet planning derives camera and physical contracts.
			plans = _plan_project(project, set(), apply=True)
			if any(p.get("held_back") for p in plans):
				raise ValueError("One or more scenes could not be planned faithfully.")
			variant["plans"] = [{"shot": p["shot"], "notes": p.get("notes", [])} for p in plans]
			if (
				index == 0
				and not request["auto_render"]
				and not _select_variant(batch, request, project.name)
			):
				return
			if not request["auto_render"]:
				variant["status"] = "Script Ready"
			else:
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					_start_keyframes(project, variant)
					frappe.db.commit()
		except Exception as exc:
			frappe.db.rollback()
			variant.update(resume_stage=variant["status"], status="Needs Attention", error=str(exc)[:1600])
			frappe.log_error(title=f"Automatic creative variant failed: {batch.name}/{index + 1}")
		if not _write(batch.name, variants, changed_index=index):
			return
		# Yield the worker between variants so image/video submission is not starved.
		_queue_prepare(batch.name, variants)
		frappe.db.commit()
		return


def _select_variant(batch, request, project_name):
	"""Navigate only to a ready script/export, preserving a newer user choice."""
	from joymedia.services.project.versions import set_working_edit

	root = request["root_project"]
	with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
			return False
		frappe.db.sql("select name from `tabMedia Project` where name=%s for update", root)
		if (frappe.db.get_value("Media Project", root, "current_edit") or root) == request[
			"expected_current"
		]:
			set_working_edit(root, project_name, request["expected_current"])
		frappe.db.commit()
		return True


def _start_keyframes(project, variant):
	from joymedia.api.storyboard import approve_project_storyboard
	from joymedia.services.keyframes.locations import missing_places, missing_views

	# The batch owns the handoff after background preparation. A cancelled batch
	# cannot later submit frames/video from an orphaned location callback.
	approve_project_storyboard(project.name)
	project.reload()
	shots = [
		frappe.get_doc("Shot", name)
		for name in frappe.get_all(
			"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name"
		)
	]
	if missing_places(project, shots) or missing_views(project, shots):
		job_id = f"joymedia-creative-locations:{project.name}"
		frappe.enqueue(
			"joymedia.services.keyframes.locations.draw_project_places",
			queue="long",
			timeout=3600,
			project_name=project.name,
			shot_names=[s.name for s in shots],
			user=frappe.session.user,
			job_id=job_id,
			deduplicate=True,
			enqueue_after_commit=True,
		)
		variant.update(status="Locations", location_job=job_id)
		return
	_submit_visual_stage(project, variant)


def _submit_visual_stage(project, variant):
	from joymedia.services.keyframes.stage import generate_keyframes
	from joymedia.services.workflows.capabilities import controls

	with pinned_execution(project.name, project.generation_pipeline):
		if "reference_only" in controls(frappe.get_doc("Generation Workflow", project.workflow)):
			variant.update(status="Rendering", generation_request=project.generate_video())
		else:
			variant.update(
				status="Keyframes", keyframe_request=generate_keyframes(project.name, draw_places=False)
			)


def advance_batches():
	"""Scheduler resumes automation through native jobs, without blocking workers."""
	for batch_name in frappe.get_all(
		"Creative Batch",
		filters={"status": ["in", ["Queued", "Planning", "Rendering", "Finishing"]]},
		pluck="name",
	):
		batch = frappe.get_doc("Creative Batch", batch_name)
		variants = frappe.parse_json(batch.variants_json)
		_queue_prepare(batch.name, variants)
		if not any(
			v["status"] in {"Locations", "Keyframes", "Rendering", "Finishing", "Exporting"} for v in variants
		):
			continue
		if not is_render_alive(f"joymedia-creative-advance:{batch.name}"):
			frappe.enqueue(
				"joymedia.services.generation.creative_batch.advance_batch",
				queue="long",
				timeout=1800,
				batch_name=batch.name,
				user=batch.owner,
				job_id=f"joymedia-creative-advance:{batch.name}",
				deduplicate=True,
				enqueue_after_commit=True,
			)


def _keyframe_ready(shot):
	if shot.consistency_status == "Passed":
		return True
	if shot.get("keyframe_status") != "Approved":
		return False
	from joymedia.services.keyframes.stage import approved_keyframe_task

	# Honor an explicit native frame approval only while its artifact/signature
	# still matches. Preserve machine findings; approval is permission to animate,
	# not a fabricated physics pass or release approval.
	return bool(approved_keyframe_task(frappe.get_doc("Shot", shot.name)))


def advance_batch(batch_name, user=None):
	from joymedia.services.audio.plan import build_audio_plan
	from joymedia.services.audio.speech import generate_voiceover
	from joymedia.services.editing.export_jobs import queue_project_timeline_export
	from joymedia.services.editing.post_production import queue_post_production_internal
	from joymedia.services.keyframes.stage import set_keyframe_approval

	batch = frappe.get_doc("Creative Batch", batch_name)
	if batch.status == "Cancelled":
		return
	frappe.set_user(batch.owner)
	variants = frappe.parse_json(batch.variants_json)
	for index, variant in enumerate(variants):
		if variant["status"] not in {"Locations", "Keyframes", "Rendering", "Finishing", "Exporting"}:
			continue
		project = frappe.get_doc("Media Project", variant["project"])
		try:
			if variant["status"] == "Locations":
				from joymedia.services.keyframes.locations import assign_places, missing_places, missing_views

				if is_render_alive(variant["location_job"]):
					continue
				shots = [
					frappe.get_doc("Shot", name)
					for name in frappe.get_all(
						"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name"
					)
				]
				if missing_places(project, shots) or missing_views(project, shots):
					raise ValueError(
						"Shared-setting preparation did not complete. Inspect the native location job before retrying."
					)
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					assign_places(project, shots)
					project.reload()
					_submit_visual_stage(project, variant)
					frappe.db.commit()
			elif variant["status"] == "Keyframes":
				active = frappe.db.exists(
					"Generation Run",
					{"media_project": project.name, "status": ["in", ["Draft", "Queued", "Running"]]},
				)
				if active:
					continue
				shots = frappe.get_all(
					"Shot",
					filters={"media_project": project.name, "is_removed": 0},
					fields=[
						"name",
						"keyframe_artifact",
						"keyframe_status",
						"consistency_status",
						"consistency_notes",
					],
				)
				if not shots or any(not s.keyframe_artifact for s in shots):
					raise ValueError("A keyframe job failed or did not produce an image.")
				if any(s.consistency_status in {"Checking", "Redrawing"} for s in shots):
					continue
				if any(not _keyframe_ready(s) for s in shots):
					raise ValueError(
						"Keyframes need review: "
						+ "; ".join(s.consistency_notes or s.name for s in shots if not _keyframe_ready(s))
					)
				for shot in shots:
					with frappe.cache.lock(
						f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10
					):
						frappe.db.commit()
						if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
							return
						set_keyframe_approval(project.name, shot.name)
						frappe.db.commit()
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					project.reload()
					request = frappe.parse_json(batch.request_json)
					with pinned_execution(project.name, request["generation_pipeline"]):
						variant.update(status="Rendering", generation_request=project.generate_video())
					frappe.db.commit()
			elif variant["status"] == "Rendering":
				run_name = variant.get("generation_request", {}).get("run")
				status = frappe.db.get_value("Generation Run", run_name, "status") if run_name else None
				if status in {"Draft", "Queued", "Running"}:
					continue
				if status != "Completed":
					raise ValueError(
						"Rendered scenes need attention. Inspect native generation evidence; quality gates remain in effect."
					)
				for cue in build_audio_plan(project.name):
					if cue["role"] == "Voiceover" and not cue["scheduled"]:
						frappe.db.commit()
						if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
							return
						generate_voiceover(project.name, cue["shot"])
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					queue_post_production_internal(project.name)
					variant["status"] = "Finishing"
					frappe.db.commit()
			elif variant["status"] == "Finishing" and project.post_production_status == "Completed":
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					queue_project_timeline_export(project.name, purpose="review")
					variant["status"] = "Exporting"
					frappe.db.commit()
			elif (
				variant["status"] == "Exporting"
				and project.export_status == "Completed"
				and project.current_output_asset_version
			):
				if index == 0 and not _select_variant(
					batch, frappe.parse_json(batch.request_json), project.name
				):
					return
				variant.update(
					status="Completed",
					output_asset_version=project.current_output_asset_version,
					video=frappe.db.get_value("Asset Version", project.current_output_asset_version, "file"),
				)
			elif project.post_production_status in {"Failed", "Cancelled"}:
				raise ValueError(project.post_production_error or "Finishing did not complete.")
			elif variant["status"] == "Exporting" and project.export_status == "Failed":
				raise ValueError(project.export_error or "Review export did not complete.")
		except Exception as exc:
			frappe.db.rollback()
			variant.update(resume_stage=variant["status"], status="Needs Attention", error=str(exc)[:1600])
		_write(batch.name, variants, changed_index=index)
