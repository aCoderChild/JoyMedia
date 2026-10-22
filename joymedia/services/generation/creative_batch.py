"""Durable orchestration over the existing workbook, generation and finishing jobs.

Batch completion means a review export. Existing identity, physical evidence,
candidate selection and release gates are never silently overridden.
"""

import copy

import frappe

from joymedia.services.generation.automation import advance_automatic_run, delivery_context, is_automatic
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
				if states <= {"Script Ready", "Completed"}
				else "Planning"
				if states & {"Queued", "Planning", "Rewriting"}
				else "Rendering"
				if states & {"Locations", "Keyframes", "Rendering"}
				else "Finishing"
				if states & {"Finishing", "Exporting"}
				else "Awaiting Review"
				if states <= {"Pictures Ready", "Script Ready", "Completed"}
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


AUTOMATIC_PICTURE_REDRAWS = 3


def _transient(exc):
	# MariaDB's optimistic-read conflict is emitted by either MySQLdb or
	# PyMySQL, depending on the worker connection. Frappe's helpers recognize
	# deadlocks/timeouts but need not classify ER_CHECKREAD (1020).
	args = getattr(exc, "args", ()) or ()
	series_conflict = bool(args and args[0] == 1020) or (
		"1020" in str(exc) and "Record has changed since last read" in str(exc)
	)
	return (
		frappe.db.is_deadlocked(exc)
		or frappe.db.is_timedout(exc)
		or series_conflict
	)


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


def _create_variant(batch, request, index, hero=None):
	from joymedia.api.projects import create_project
	from joymedia.services.project.versions import (
		copy_control_reference,
		family,
		next_video_number,
		organize_edits,
	)

	source = frappe.get_doc("Media Project", batch.source_project)
	root = family(source)
	number = next_video_number(root)
	# A variant is another video of the same project, not a project of its own.
	project = create_project(root.project_name, request["product_name"])
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
		if (
			hero
			and row["reference_role"] == "Product"
			and (row.get("identity_key") or row["reference_key"]) != hero
		):
			# One featured product per video keeps its packaging identical in every shot.
			continue
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
		[{"project": project.name, "label": f"Video {number}", "kind": "Experiment"}],
	)
	frappe.db.commit()
	persist_execution_pin(project.name, request["generation_pipeline"])
	return project


def _storyboard_with_frames(batch, variant, shots):
	"""Rebuild the variant's template workbook with each scene's drawn first frame."""
	from frappe.utils.file_manager import save_file

	from joymedia.services.planning.creative import script_workbook

	pictures = {}
	for shot in shots:
		control = _explicit_first_frame(shot.name)
		url = (
			frappe.db.get_value("Asset Version", control, "file")
			if control
			else shot.keyframe_artifact
			and frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
		)
		if url:
			pictures[shot.shot_number] = frappe.get_doc("File", {"file_url": url}).get_full_path()
	if not pictures:
		return
	project = frappe.get_doc("Media Project", variant["project"])
	file = save_file(
		f"{batch.name}-variant-{variant['index']}-storyboard.xlsx",
		script_workbook(variant["script"], project, pictures=pictures),
		"Media Project",
		project.name,
		is_private=1,
	)
	variant["workbook"] = file.file_url


def _name_video(project, script):
	"""Label the video by its concept and fill a product name the inputs did not give."""
	label = (project.version_label or "").split(" · ")[0]
	if label.startswith("Video ") and script.get("title"):
		project.db_set("version_label", f"{label} · {script['title']}"[:100], update_modified=False)
	if script.get("product_name"):
		for name in (project.name, project.version_of):
			if name and not frappe.db.get_value("Media Project", name, "product_name"):
				frappe.db.set_value(
					"Media Project", name, "product_name", script["product_name"], update_modified=False
				)


def prepare_batch(batch_name):
	"""Background CPU planning. Inference never holds a database or Redis lock."""
	from frappe.utils.file_manager import save_file

	from joymedia.api.storyboard import _plan_project, import_storyboard_workbook
	from joymedia.services.intake.action_reference import ensure_action_analysis
	from joymedia.services.intake.cinematography import ensure_project_camera_analysis
	from joymedia.services.planning.creative import (
		draft_script,
		reference_inventory,
		script_exemplars,
		script_workbook,
	)

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
				else _create_variant(batch, request, index, variant.get("hero_product"))
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
					examples=script_exemplars(request.get("example_workbooks"), index),
					hero_product=variant.get("hero_product"),
					revision=variant.get("revision"),
					language=request.get("language"),
					require_clean=is_automatic(request),
				)
				if any(
					v.get("script", {}).get("logline", "").casefold() == script["logline"].casefold()
					for v in variants[:index]
				):
					raise ValueError("The proposed variant repeats an earlier concept.")
				variant["script"] = script
				_name_video(project, script)
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
				# The workbook is generated by the writer. Its camera_move cells are
				# proposals, not client-authored instructions; the shared shot policy
				# resolves them against action, framing and available endpoints.
				source = frappe.parse_json(project.storyboard_source_json or "{}") or {}
				source["generation_origin"] = "ai_director"
				project.db_set("storyboard_source_json", frappe.as_json(source))
				project.storyboard_source_json = frappe.as_json(source)
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
			# Every storyboard comes with its scenes' first frames, not words only; the
			# video waits for the picture review either way.
			with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
				frappe.db.commit()
				if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
					return
				_start_keyframes(project, variant, request, batch.name)
				frappe.db.commit()
		except Exception as exc:
			frappe.db.rollback()
			if _transient(exc):
				# A concurrent write conflict: the scheduler resumes this variant next minute.
				return
			variant.update(resume_stage=variant["status"], status="Needs Attention", error=str(exc)[:1600])
			frappe.log_error(title=f"Automatic creative variant failed: {batch.name}/{index + 1}")
		if not _write(batch.name, variants, changed_index=index):
			return
		# Yield the worker between variants so image/video submission is not starved.
		_queue_prepare(batch.name, variants)
		frappe.db.commit()
		return


def revise_variant(batch_name, position, notes):
	"""Rewrite a not-yet-rendered script from reviewer notes.

	Notes on named scenes at picture review rewrite those scenes in place; other
	notes produce a fresh version project. Earlier scripts stay as history and
	nothing already rendered changes.
	"""
	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		batch = frappe.get_doc("Creative Batch", batch_name)
		if batch.status == "Cancelled":
			raise ValueError("A stopped batch cannot be revised.")
		variants = frappe.parse_json(batch.variants_json)
		if position >= len(variants):
			raise ValueError("Choose an existing video.")
		variant = variants[position]
		if variant["status"] not in {"Script Ready", "Pictures Ready"} and not (
			variant["status"] == "Needs Attention"
			and variant.get("script")
			and not variant.get("generation_request")
		):
			raise ValueError("Only a script that has not been rendered yet can be rewritten.")
		variant.setdefault("history", []).append(
			{k: variant.get(k) for k in ("project", "workbook", "script", "title") if variant.get(k)}
		)
		in_place = variant["status"] == "Pictures Ready" and all(n.get("scene") for n in notes)
		if in_place:
			# Notes on named scenes at picture review: rewrite just those scenes in
			# this project and keep every other scene and its picture.
			variant["scene_revision"] = {"notes": notes, "by": frappe.session.user}
			variant["status"] = "Rewriting"
		else:
			variant["revision"] = {"script": variant["script"], "notes": notes, "by": frappe.session.user}
			for key in (
				"project",
				"workbook",
				"script",
				"title",
				"plans",
				"error",
				"resume_stage",
				"location_job",
				"keyframe_request",
				"picture_notes",
				"auto_redraws",
			):
				variant.pop(key, None)
			variant["status"] = "Queued"
	if in_place:
		_write(batch_name, variants, changed_index=position)
		frappe.enqueue(
			"joymedia.services.generation.creative_batch.rewrite_scenes_in_place",
			queue="long",
			timeout=3600,
			batch_name=batch_name,
			position=position,
			job_id=f"joymedia-creative-rewrite:{batch_name}:{position}",
			deduplicate=True,
			enqueue_after_commit=True,
		)
	else:
		_write(batch_name, variants, "Planning", changed_index=position)
		_queue_prepare(batch_name, variants)
	frappe.db.commit()
	return {"batch": batch_name, "index": position + 1, "status": variants[position]["status"]}


def _locked_variant(batch_name, position, *statuses):
	batch = frappe.get_doc("Creative Batch", batch_name)
	if batch.status == "Cancelled":
		raise ValueError("A stopped batch cannot continue.")
	variants = frappe.parse_json(batch.variants_json)
	if position >= len(variants) or variants[position]["status"] not in statuses:
		raise ValueError("This video is not waiting for that review.")
	return batch, variants, variants[position]


def approve_variant_pictures(batch_name, position):
	"""The reviewer accepts every scene picture: approve them and make the video."""
	from joymedia.services.keyframes.stage import set_keyframe_approval

	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		batch, variants, variant = _locked_variant(batch_name, position, "Pictures Ready")
		project = frappe.get_doc("Media Project", variant["project"])
		shots = frappe.get_all(
			"Shot",
			filters={"media_project": project.name, "is_removed": 0},
			fields=["name", "keyframe_artifact", "keyframe_status"],
		)
		if not shots or any(not s.keyframe_artifact for s in shots):
			raise ValueError("Redraw the scenes that have no picture before approving.")
		for shot in shots:
			if shot.keyframe_status != "Approved":
				set_keyframe_approval(project.name, shot.name)
		project.reload()
		request = frappe.parse_json(batch.request_json)
		with (
			pinned_execution(project.name, request["generation_pipeline"]),
			delivery_context(request, batch.name),
		):
			variant.update(status="Rendering", generation_request=project.generate_video(), picture_notes={})
		frappe.db.commit()
	_write(batch_name, variants, changed_index=position)
	return {"batch": batch_name, "index": position + 1, "status": "Rendering"}


def redraw_variant_picture(batch_name, position, shot_name):
	"""Draw one scene picture again; the video waits for the new picture."""
	from joymedia.services.keyframes.stage import generate_keyframes

	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		# Several pictures can be redrawn one after another; each scene guards its own job.
		batch, variants, variant = _locked_variant(batch_name, position, "Pictures Ready", "Keyframes")
		if frappe.db.get_value("Shot", shot_name, "media_project") != variant["project"]:
			raise ValueError("That scene belongs to another video.")
		request = frappe.parse_json(batch.request_json)
		with pinned_execution(variant["project"], request["generation_pipeline"]):
			variant.update(
				status="Keyframes",
				keyframe_request=generate_keyframes(variant["project"], [shot_name], draw_places=False),
			)
		frappe.db.commit()
	_write(batch_name, variants, changed_index=position)
	return {"batch": batch_name, "index": position + 1, "status": "Keyframes"}


def held_scene_clips(project_name):
	"""Each scene still without a selected take, with the clip a person can review.

	A finished take the automatic check could not qualify is offered first
	(accepting it selects it); otherwise the latest held clip, which may be
	accepted only under the same rule as retaining held footage by hand.
	"""
	from joymedia.services.consistency.repair import held_take_review_candidate
	from joymedia.services.generation.takes import scene_takes
	from joymedia.services.review.admission import report_for

	clips = []
	for shot in frappe.get_all(
		"Shot",
		filters={
			"media_project": project_name,
			"is_removed": 0,
			"selected_output_asset_version": ["is", "not set"],
		},
		fields=["name", "shot_name", "shot_number"],
		order_by="shot_number asc",
	):
		clip = {"shot": shot.name, "shot_name": shot.shot_name, "shot_number": shot.shot_number}
		row = frappe.db.sql(
			"""select a.name, a.creation, f.frappe_file from `tabGeneration Attempt` a
			join `tabGeneration Task` t on a.generation_task = t.name
			join `tabGeneration Artifact` f on f.generation_attempt = a.name and f.artifact_role = 'Primary Video'
			where t.shot = %s and a.status = 'Failed' order by a.creation desc limit 1""",
			shot.name,
			as_dict=True,
		)
		take = _current_take(shot.name, scene_takes(project_name, shot.name))
		unlocked = (
			[
				"Product print not locked (the pack moved too much to track): compare its label with your product photo."
			]
			if frappe.db.exists("File", {"file_name": ["like", f"%-{shot.name}-product-unlocked%.json"]})
			else []
		)
		# Offer the newest footage: a take composed for an earlier direction, or
		# older than the latest held render, is not what the reviewer must judge.
		if take and not (row and row[0].creation > frappe.db.get_value("Asset Version", take, "creation")):
			version = take
			clip.update(
				asset_version=version,
				url=frappe.db.get_value("Asset Version", version, "file"),
				findings=unlocked,
				reviewable=True,
			)
			clips.append(clip)
			continue
		report = report_for(row[0].name) if row else None
		clip.update(
			attempt=row[0].name if row else None,
			url=row[0].frappe_file if row else None,
			findings=unlocked
			+ list(
				dict.fromkeys(
					r.get("reason") or r.get("claim")
					for r in (report or {}).get("results", [])
					if r.get("verdict") != "supported" and r.get("id") != "geometry_qualification"
				)
			)[:3],
			reviewable=bool(report and held_take_review_candidate(report)),
		)
		clips.append(clip)
	return clips


def _current_take(shot_name, takes):
	"""The newest take still made for the scene's current direction."""
	from joymedia.services.review.lineage import take_direction_changed

	shot = frappe.get_doc("Shot", shot_name)
	for take in reversed(takes):
		shot.selected_output_asset_version = take.name  # evaluated in memory only
		if not take_direction_changed(shot):
			return take.name
	return None


def accept_held_clip(batch_name, position, shot_name, note, attempt_name=None, asset_version=None):
	"""A reviewer watched a scene's clip and accepts it as the scene's take."""
	from pathlib import Path

	from joymedia.services.generation.takes import retain_held_take_for_review, use_reviewed_take
	from joymedia.services.review.admission import digest

	batch = frappe.get_doc("Creative Batch", batch_name)
	variants = frappe.parse_json(batch.variants_json)
	variant = variants[position]
	if batch.status == "Cancelled" or variant["status"] != "Needs Attention" or not variant.get("project"):
		raise ValueError("Only a stopped video's held scenes can be reviewed.")
	if frappe.db.get_value("Shot", shot_name, "media_project") != variant["project"]:
		raise ValueError("That scene belongs to another video.")
	current = frappe.db.get_value("Shot", shot_name, "selected_output_asset_version")
	if not asset_version:
		artifact = frappe.get_doc(
			"Generation Artifact", {"generation_attempt": attempt_name, "artifact_role": "Primary Video"}
		)
		source = digest(
			Path(frappe.get_doc("File", {"file_url": artifact.frappe_file}).get_full_path()).read_bytes()
		)
		asset_version = retain_held_take_for_review(
			variant["project"], shot_name, attempt_name, current, source, note
		)["asset_version"]
	use_reviewed_take(variant["project"], shot_name, asset_version, current)
	variant.setdefault("reviewed_clips", []).append(
		{"shot": shot_name, "asset_version": asset_version, "note": note, "by": frappe.session.user}
	)
	_write(batch_name, variants, changed_index=position)
	return {"shot": shot_name, "asset_version": asset_version}


def rerender_failed_scenes(variant, request):
	from joymedia.services.generation.takes import _start_takes_run

	project = frappe.get_doc("Media Project", variant["project"])
	# A transient batch-state failure can happen *after* the native run has
	# completed but before its takes were selected. Recover those finished takes
	# before deciding which scenes need another expensive GPU render.
	prior_run = (variant.get("generation_request") or {}).get("run")
	if is_automatic(request) and prior_run and frappe.db.get_value("Generation Run", prior_run, "status") in {
		"Completed", "Failed"
	}:
		_select_automatic_outputs(project.name, prior_run, variant)
	failed = frappe.get_all(
		"Shot",
		filters={
			"media_project": project.name,
			"is_removed": 0,
			"selected_output_asset_version": ["is", "not set"],
		},
		pluck="name",
	)
	if not failed:
		return
	with pinned_execution(project.name, request["generation_pipeline"]), delivery_context(request):
		variant["generation_request"] = _start_takes_run(project, failed, retry_reason="Manual Retry")


def rewrite_scenes_in_place(batch_name, position):
	"""Background job: rewrite only the noted scenes, re-plan and redraw only them."""
	import uuid

	from frappe.utils.file_manager import save_file

	from joymedia.api.storyboard import _plan_project, approve_project_storyboard
	from joymedia.services.keyframes.stage import generate_keyframes
	from joymedia.services.planning.creative import draft_script, script_exemplars, script_workbook
	from joymedia.services.planning.plan_parsing import _rescale_motion_plan
	from joymedia.services.planning.timed_actions import read_timed_actions
	from joymedia.services.planning.workbook import parse_storyboard_workbook

	batch = frappe.get_doc("Creative Batch", batch_name)
	frappe.set_user(batch.owner)
	request = frappe.parse_json(batch.request_json)
	variants = frappe.parse_json(batch.variants_json)
	variant = variants[position]
	if batch.status == "Cancelled" or variant["status"] != "Rewriting":
		return
	try:
		project = frappe.get_doc("Media Project", variant["project"])
		old = variant["script"]
		notes = variant["scene_revision"]["notes"]
		script = draft_script(
			project,
			nonce=uuid.uuid4().hex,
			examples=script_exemplars(request.get("example_workbooks"), position),
			hero_product=variant.get("hero_product"),
			revision={"script": old, "notes": notes},
			language=request.get("language"),
		)
		changed = sorted({n["scene"] - 1 for n in notes if 0 < n["scene"] <= len(old["scenes"])})
		for i in range(len(script["scenes"])):
			if i not in changed:
				script["scenes"][i] = old["scenes"][i]
				continue
			# Same beat name and duration: the shot, its timeline slot and the film length stay.
			scene, duration = script["scenes"][i], old["scenes"][i]["duration_seconds"]
			phases = read_timed_actions(scene["action"])
			plan = {"duration_seconds": duration, "motion_plan": {"actions": phases}}
			_rescale_motion_plan(plan, phases[-1]["end"])
			scene.update(beat_name=old["scenes"][i]["beat_name"], duration_seconds=duration)
			scene["action"] = "\n".join(
				f"[{row['start']:.9f}-{row['end']:.9f}s] {row['action']}"
				for row in plan["motion_plan"]["actions"]
			)
		script["duration_seconds"] = old["duration_seconds"]
		from joymedia.services.planning.creative import vary_against_neighbours

		# The camera director ran before the untouched scenes were restored: vary
		# each rewritten scene against its real neighbours (whose pictures stay).
		script.setdefault("camera_adjustments", []).extend(
			change for i in changed for change in vary_against_neighbours(script["scenes"], i)
		)
		content = script_workbook(script, project)
		file = save_file(
			f"{batch.name}-variant-{position + 1}-r{len(variant.get('history', []))}.xlsx",
			content,
			"Media Project",
			project.name,
			is_private=1,
		)
		parsed = parse_storyboard_workbook(file.get_full_path())["demos"][0]["scenes"]
		source = frappe.parse_json(project.storyboard_source_json)
		for i in changed:
			source["selected_demo"]["scenes"][i] = parsed[i]
		project.db_set("storyboard_source_json", frappe.as_json(source))
		shots = frappe.get_all(
			"Shot",
			filters={"media_project": project.name, "is_removed": 0},
			pluck="name",
			order_by="shot_number asc",
		)
		wanted = {shots[i] for i in changed}
		project.reload()
		_plan_project(project, wanted, apply=True)
		approve_project_storyboard(project.name)
		with pinned_execution(project.name, request["generation_pipeline"]):
			request_run = generate_keyframes(project.name, sorted(wanted))
		variant.update(
			script=script,
			workbook=file.file_url,
			status="Keyframes",
			keyframe_request=request_run,
			scene_revision=None,
			error="",
		)
		variant["auto_redraws"] = [s for s in variant.get("auto_redraws", []) if s not in wanted]
	except Exception as exc:
		frappe.db.rollback()
		if _transient(exc):
			return
		variant.update(resume_stage="Keyframes", status="Needs Attention", error=str(exc)[:1600])
		frappe.log_error(title=f"Scene rewrite failed: {batch_name}/{position + 1}")
	_write(batch_name, variants, changed_index=position)


def start_variant_render(batch_name, position):
	"""Continue a reviewed "Script Ready" variant through the native visual stages."""
	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		batch = frappe.get_doc("Creative Batch", batch_name)
		if batch.status == "Cancelled":
			raise ValueError("A stopped batch cannot render.")
		variants = frappe.parse_json(batch.variants_json)
		if position >= len(variants) or variants[position]["status"] != "Script Ready":
			raise ValueError("Only a written, not yet rendered script can be approved for video.")
		variant = variants[position]
		project = frappe.get_doc("Media Project", variant["project"])
		_start_keyframes(project, variant, frappe.parse_json(batch.request_json), batch.name)
		frappe.db.commit()
	_write(batch_name, variants, changed_index=position)
	return {"batch": batch_name, "index": position + 1, "status": variant["status"]}


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


def _start_keyframes(project, variant, request=None, batch_name=None):
	from joymedia.api.storyboard import approve_project_storyboard
	from joymedia.services.keyframes.locations import assign_places, missing_places, missing_views

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
	assign_places(project, shots)
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
	_submit_visual_stage(project, variant, request, batch_name)


def _submit_visual_stage(project, variant, request=None, batch_name=None):
	from joymedia.services.keyframes.stage import generate_keyframes
	from joymedia.services.workflows.capabilities import controls

	with (
		pinned_execution(project.name, project.generation_pipeline),
		delivery_context(request or {}, batch_name),
	):
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


def _unprotected(shot):
	"""Whether the picture's product label could not be locked to the original photo."""
	lock = (
		frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "product_lock_json")
		if shot.get("keyframe_artifact")
		else None
	)
	return bool(lock and (frappe.parse_json(lock) or {}).get("unprotected"))


def _explicit_first_frame(shot_name):
	return frappe.db.get_value(
		"Shot Reference", {"parent": shot_name, "reference_role": "first_frame"}, "asset_version"
	)


def _keyframe_ready(shot):
	if _explicit_first_frame(shot.name):
		return True  # an explicit project-selected first frame supersedes generated still evidence
	if shot.consistency_status == "Passed" and not _unprotected(shot):
		return True
	if shot.get("keyframe_status") != "Approved":
		return False
	from joymedia.services.keyframes.stage import approved_keyframe_task

	# Honor an explicit native frame approval only while its artifact/signature
	# still matches. Preserve machine findings; approval is permission to animate,
	# not a fabricated physics pass or release approval.
	return bool(approved_keyframe_task(frappe.get_doc("Shot", shot.name)))


def _selected_review_outputs(project_name):
	"""Resume finishing after native take review/repair, without rewriting failed jobs."""
	from joymedia.services.generation.takes import scene_takes
	from joymedia.services.review.lineage import take_direction_changed

	if frappe.db.exists(
		"Generation Run", {"media_project": project_name, "status": ["in", ["Draft", "Queued", "Running"]]}
	):
		return False
	shots = frappe.get_all("Shot", filters={"media_project": project_name, "is_removed": 0}, pluck="name")
	if not shots:
		return False
	for name in shots:
		shot = frappe.get_doc("Shot", name)
		selected = shot.selected_output_asset_version
		if not selected or selected not in {row.name for row in scene_takes(project_name, name)}:
			return False
		attempt = frappe.db.get_value("Asset Version", selected, "source_generation_attempt")
		task = frappe.db.get_value("Generation Attempt", attempt, "generation_task") if attempt else None
		if (
			not task
			or frappe.db.get_value("Generation Task", task, "shot") != name
			or take_direction_changed(shot)
		):
			return False
	return True


def _select_automatic_outputs(project_name, run_name, variant):
	"""Select only outputs from this automatic run for its review export.

	A source-art warning stays a warning. No admission report or brand approval is
	changed, and older footage is never substituted for a failed current render.
	"""
	from joymedia.services.generation.takes import scene_takes, select_scene_take

	snapshot = frappe.parse_json(
		frappe.db.get_value("Generation Run", run_name, "project_snapshot_json") or "{}"
	)
	if not snapshot.get("automatic_delivery"):
		return
	previous = frappe.flags.get("joymedia_defer_finishing")
	frappe.flags.joymedia_defer_finishing = True
	try:
		for row in frappe.get_all(
			"Shot",
			filters={"media_project": project_name, "is_removed": 0},
			fields=["name", "selected_output_asset_version"],
			order_by="shot_number",
		):
			if row.selected_output_asset_version:
				continue
			takes = scene_takes(project_name, row.name)
			current = _current_take(row.name, takes)
			attempt = (
				frappe.db.get_value("Asset Version", current, "source_generation_attempt") if current else None
			)
			task = frappe.db.get_value("Generation Attempt", attempt, "generation_task") if attempt else None
			if not task or frappe.db.get_value("Generation Task", task, "generation_run") != run_name:
				continue
			select_scene_take(
				project_name, row.name, next(i for i, take in enumerate(takes, 1) if take.name == current)
			)
			variant.setdefault("automatic_selections", []).append(
				{"shot": row.name, "asset_version": current, "quality_review": "deferred"}
			)
	finally:
		frappe.flags.joymedia_defer_finishing = previous


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
	request = frappe.parse_json(batch.request_json)
	automatic = is_automatic(request)
	for index, variant in enumerate(variants):
		if variant["status"] not in {"Locations", "Keyframes", "Rendering", "Finishing", "Exporting"}:
			continue
		project = frappe.get_doc("Media Project", variant["project"])
		try:
			if automatic and variant["status"] in {"Keyframes", "Rendering"}:
				stage_request = (
					variant.get(
						"keyframe_request" if variant["status"] == "Keyframes" else "generation_request"
					)
					or {}
				)
				if stage_request.get("run"):
					advance_automatic_run(stage_request["run"])
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
					_submit_visual_stage(project, variant, request, batch.name)
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
						"shot_number",
						"keyframe_artifact",
						"keyframe_status",
						"consistency_status",
						"consistency_notes",
					],
				)
				if not shots:
					raise ValueError("A keyframe job failed or did not produce an image.")
				if any(s.consistency_status in {"Checking", "Redrawing"} for s in shots):
					continue
				if automatic and any(
					s.consistency_status == "Needs Review"
					and not _explicit_first_frame(s.name)
					and any(
						label in (s.consistency_notes or "")
						for label in ("Critical geometry:", "Critical framing:", "Critical prop:")
					)
					for s in shots
				):
					raise ValueError(
						"A first frame still has an unsupported character/product geometry after bounded redraws."
					)
				redrawn = variant.setdefault("auto_redraws", [])
				missing = [
					s.name
					for s in shots
					if not s.keyframe_artifact and redrawn.count(s.name) < AUTOMATIC_PICTURE_REDRAWS
				]
				if missing:
					# Picture generation is stochastic (about half of first drawings fail a
					# check): draw each failed picture again, through the same checks,
					# a bounded number of times before asking a person.
					from joymedia.services.keyframes.stage import generate_keyframes

					with frappe.cache.lock(
						f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10
					):
						frappe.db.commit()
						if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
							return
						with (
							pinned_execution(project.name, project.generation_pipeline),
							delivery_context(request, batch.name),
						):
							variant["keyframe_request"] = generate_keyframes(
								project.name, missing, draw_places=False, automatic=True
							)
						redrawn.extend(missing)
						frappe.db.commit()
					_write(batch.name, variants, changed_index=index)
					continue
				if any(not s.keyframe_artifact for s in shots):
					raise ValueError(
						"First-frame generation exhausted its retries without producing an image."
					)
				if not automatic and any(not _keyframe_ready(s) for s in shots):
					# A person decides: unqualified or missing pictures are never approved
					# automatically. The reviewer approves them or asks for a redraw.
					variant["status"] = "Pictures Ready"
					_storyboard_with_frames(batch, variant, shots)
					variant["picture_notes"] = {
						s.name: s.consistency_notes or ("" if s.keyframe_artifact else "No picture yet.")
						for s in shots
						if not s.keyframe_artifact or not _keyframe_ready(s)
					}
					_write(batch.name, variants, changed_index=index)
					continue
				_storyboard_with_frames(batch, variant, shots)
				if automatic:
					variant["frame_authorization"] = {
						"mode": "automatic",
						"quality_review": "deferred",
						"artifacts": {s.name: _explicit_first_frame(s.name) or s.keyframe_artifact for s in shots},
					}
				for shot in shots:
					if _explicit_first_frame(shot.name):
						continue  # the source control is already the selected video input
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
					with (
						pinned_execution(project.name, request["generation_pipeline"]),
						delivery_context(request, batch.name),
					):
						variant.update(status="Rendering", generation_request=project.generate_video())
					frappe.db.commit()
			elif variant["status"] == "Rendering":
				run_name = variant.get("generation_request", {}).get("run")
				status = frappe.db.get_value("Generation Run", run_name, "status") if run_name else None
				if status in {"Draft", "Queued", "Running"}:
					continue
				if automatic and run_name and status in {"Completed", "Failed"}:
					_select_automatic_outputs(project.name, run_name, variant)
				if status != "Completed" and not (
					status == "Failed" and _selected_review_outputs(project.name)
				):
					if automatic and status == "Failed" and not variant.get("automatic_render_retry"):
						rerender_failed_scenes(variant, request)
						variant["automatic_render_retry"] = True
						_write(batch.name, variants, changed_index=index)
						continue
					raise ValueError(
						"Rendered scenes need attention. Inspect native generation evidence; quality gates remain in effect."
					)
				missing_outputs = frappe.get_all(
					"Shot",
					filters={
						"media_project": project.name,
						"is_removed": 0,
						"selected_output_asset_version": ["is", "not set"],
					},
					pluck="name",
				)
				if missing_outputs:
					raise ValueError(
						"Rendered scenes have no selected output yet: "
						+ ", ".join(missing_outputs)
						+ ". Output selection must finish before narration and editing."
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
			if _transient(exc):
				# A concurrent write conflict: the next scheduler tick retries this stage.
				continue
			variant.update(resume_stage=variant["status"], status="Needs Attention", error=str(exc)[:1600])
		_write(batch.name, variants, changed_index=index)
