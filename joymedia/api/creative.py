"""Product-reference automation entry points, shared by browser and integrations."""

import math
import uuid

import frappe


def _named(code):
	code = str(code or "").lower()
	return (
		"Vietnamese" if code.startswith(("vi", "vietnam")) else "English" if code.startswith("en") else None
	)


def _review_context(project):
	"""Snapshot unresolved first-party feedback; never resolve it by copying it."""
	from joymedia.services.project.versions import family
	from joymedia.services.review.release_feedback import unresolved_cut_feedback

	root = family(project)
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project.name},
		fields=["enabled", "source_asset_version", "track_type"],
	)
	affected = set(unresolved_cut_feedback(project.name, clips))
	notes = [
		{
			"source": r.name,
			"category": r.category,
			"text": r.feedback,
			"scope": "Current"
			if r.asset_version == project.current_output_asset_version or r.name in affected
			else "Historical",
		}
		for r in frappe.get_all(
			"Video Review Feedback",
			filters={"media_project": root.name, "status": ["in", ["Open", "Investigating"]]},
			fields=["name", "category", "feedback", "asset_version"],
			order_by="creation desc",
			limit=12,
		)
	]
	notes.extend(
		{
			"source": r.name,
			"category": "Scene",
			"text": r.comment,
			"scope": "Current"
			if r.output_asset_version == frappe.db.get_value("Shot", r.shot, "selected_output_asset_version")
			else "Historical",
		}
		for r in frappe.get_all(
			"Review Comment",
			filters={"media_project": project.name, "status": "Open"},
			fields=["name", "comment", "shot", "output_asset_version"],
			order_by="creation desc",
			limit=12,
		)
	)
	return notes


@frappe.whitelist(methods=["POST"])
def create_product_batch(
	source_project,
	count=1,
	auto_render=True,
	reference_keys=None,
	direction=None,
	duration_seconds=None,
	aspect_ratio=None,
	hero_products=None,
	example_workbooks=None,
	language=None,
	delivery_mode=None,
):
	"""Queue `count` AI-written videos. Each video features ONE hero product so its
	packaging never changes between shots; several heroes rotate across the videos.
	Example workbooks are the client's own scripts, used as style references."""
	from joymedia.services.intake.references import brand, preservation_modes
	from joymedia.services.project.formats import delivery_dimensions, orientation, parse_ratio, ratio_label

	project = frappe.get_doc("Media Project", source_project)
	project._require_write_access()
	from joymedia.services.intake.view_sheet import split_project_view_sheets

	# A character turnaround sheet would be drawn as several characters: use its separate views.
	if split_project_view_sheets(project.name):
		project.reload()
	from joymedia.services.partners import is_reviewer, require_generation

	if is_reviewer():
		require_generation()
	if type(count) is bool or str(count) not in {str(i) for i in range(1, 21)}:
		raise ValueError("Choose one to twenty video variants.")
	count = int(count)
	auto_render = str(auto_render).lower() in {"1", "true", "yes", "on"}
	delivery_mode = delivery_mode or ("automatic" if auto_render else "assisted")
	if delivery_mode not in {"automatic", "assisted"}:
		raise ValueError("Choose automatic delivery or assisted review.")
	if delivery_mode == "automatic" and not auto_render:
		raise ValueError("Automatic delivery requires video generation to be enabled.")
	keys = frappe.parse_json(reference_keys) if isinstance(reference_keys, str) else reference_keys
	if keys is not None and (not isinstance(keys, list) or any(not isinstance(k, str) for k in keys)):
		raise ValueError("Reference keys must be a list.")
	# A reference is deliberately allowed to be role ``General`` when its
	# analysis has not promoted it to a product/character/environment.  Action
	# endpoints, supported poses and source-art macro controls are commonly
	# stored that way; dropping them here made a references-only batch lose the
	# very evidence the Director needed for a physical action.  The downstream
	# reference planner decides how each role is used per scene.
	allowed = {
		"Product",
		"Character",
		"Person",
		"Logo",
		"Environment",
		"Motion",
		"Style",
		"Composition",
		"Audio",
		"General",
	}
	references = [
		{
			key: row.get(key)
			for key in (
				"reference_key",
				"identity_key",
				"asset_version",
				"reference_role",
				"motion_reference_use",
				"label",
				"relative_size",
				"keep_rule",
			)
		}
		for row in project.selected_media
		if row.reference_role in allowed and (keys is None or row.reference_key in keys)
	]
	if keys is not None and set(keys) - {r["reference_key"] for r in references}:
		raise ValueError("Choose only selected product, mascot, person, logo or creative-reference keys.")
	if not any(row["reference_role"] == "Product" for row in references):
		raise ValueError("Select product images before automatic generation.")
	products = list(
		dict.fromkeys(
			r["identity_key"] or r["reference_key"] for r in references if r["reference_role"] == "Product"
		)
	)
	heroes = (
		frappe.parse_json(hero_products)
		if isinstance(hero_products, str) and hero_products != "all"
		else hero_products
	)
	if heroes in (None, []):
		heroes = products[:1]
	elif heroes == "all":
		heroes = products
	if not isinstance(heroes, list) or len(heroes) > 20 or set(heroes) - set(products):
		raise ValueError("Choose the featured products from the selected product images.")
	examples = (
		frappe.parse_json(example_workbooks) if isinstance(example_workbooks, str) else example_workbooks
	)
	examples = examples or []
	if not isinstance(examples, list) or len(examples) > 5:
		raise ValueError("Attach up to five example scripts.")
	for name in examples:
		file = frappe.get_doc("File", name)
		file.check_permission("read")
		if not str(file.file_name or "").lower().endswith(".xlsx"):
			raise ValueError("Example scripts must be .xlsx workbooks.")
	modes = preservation_modes(project)
	from joymedia.services.workflows.capabilities import execution_spec

	defaults = (
		execution_spec(frappe.get_doc("Generation Workflow", project.workflow)).get("reference_defaults", {})
		if project.workflow
		else {}
	)
	if not isinstance(defaults, dict) or any(
		mode not in {"source_pixels", "reference_guided"} for mode in defaults.values()
	):
		raise ValueError("Workflow reference defaults require declared preservation modes.")
	frozen_modes = {
		r["asset_version"]: modes.get(r["asset_version"]) or defaults.get(r["reference_role"])
		for r in references
		if modes.get(r["asset_version"]) or defaults.get(r["reference_role"])
	}
	duration = (
		duration_seconds if duration_seconds not in (None, "") else (project.total_duration_seconds or None)
	)
	if duration is not None:
		if type(duration) is bool:
			raise ValueError("Duration must be a number of seconds.")
		duration = float(duration)
		if not math.isfinite(duration) or not 1 <= duration <= 60:
			raise ValueError("Duration must be between one and sixty seconds.")
	ratio = (
		parse_ratio(aspect_ratio)
		if aspect_ratio
		else parse_ratio(ratio_label(project.delivery_width, project.delivery_height))
	)
	if aspect_ratio and not ratio:
		raise ValueError("Specify an aspect ratio such as 16:9 or 4:5.")
	width, height = (
		delivery_dimensions(ratio, min(project.delivery_width or 720, project.delivery_height or 720))
		if ratio
		else (None, None)
	)
	if not isinstance(direction or "", str) or len(direction or "") > 4000:
		raise ValueError("Creative direction must be a short optional description.")
	request = {
		"version": 1,
		"review_notes": _review_context(project),
		"references": references,
		"reference_preservation_modes": frozen_modes,
		"count": count,
		"auto_render": auto_render,
		"delivery_mode": delivery_mode,
		# First-frame repair is autonomous in both delivery modes. Assisted
		# delivery still keeps the final review/release gates.
		"auto_first_frames": True,
		"direction": direction or "",
		"duration_seconds": duration or None,
		"width": width,
		"height": height,
		"delivery_preset": orientation(ratio) if ratio else None,
		"product_name": project.product_name or "",
		"hero_products": heroes,
		# Language of what viewers hear and read; production prompts stay English.
		# Explicit choice, else the example scripts' language (detected when writing), else the user's.
		"language": _named(language) or (None if examples else _named(frappe.local.lang)),
		"example_workbooks": examples,
		"workflow": project.workflow,
		"generation_pipeline": project.generation_pipeline,
		"render_profile": {
			key: project.get(key)
			for key in ("export_quality", "quality_mode", "character_mode", "show_captions")
		},
		"brand": {
			k: v
			for k, v in brand(project).items()
			if k in {"claims", "avoid", "mandatories", "camera_style", "camera_grammar"}
		},
	}
	from joymedia.services.project.versions import family

	root = family(project)
	request.update(root_project=root.name, expected_current=root.current_edit or root.name)
	variants = [
		{
			"index": i + 1,
			"status": "Queued",
			"nonce": uuid.uuid4().hex,
			"hero_product": heroes[i % len(heroes)],
		}
		for i in range(count)
	]
	batch = frappe.get_doc(
		{
			"doctype": "Creative Batch",
			"owner": project.owner,
			"requested_by": frappe.session.user,
			"source_project": project.name,
			"status": "Queued",
			"request_json": frappe.as_json(request),
			"variants_json": frappe.as_json(variants),
		}
	).insert(ignore_permissions=True)
	from joymedia.services.generation.availability import partner_batch_waits_for_gpu
	from joymedia.services.generation.creative_batch import _planning_queue

	waiting_for_gpu = partner_batch_waits_for_gpu(batch.owner)
	if not waiting_for_gpu:
		frappe.enqueue(
			"joymedia.services.generation.creative_batch.prepare_batch",
			queue=_planning_queue(),
			timeout=3600,
			batch_name=batch.name,
			position=0,
			job_id=f"joymedia-creative-prepare:{batch.name}:0",
			deduplicate=True,
			enqueue_after_commit=True,
		)
	return {"batch": batch.name, "status": "Queued", "count": count, "waiting_for_gpu": waiting_for_gpu}


def _prepared_assets(variant):
	"""Expose the scene-led view candidates as reviewable batch intermediates."""
	project_name = variant.get("project")
	if not project_name or not frappe.db.exists("Media Project", project_name):
		return []
	project = frappe.get_doc("Media Project", project_name)
	selected = {row.get("reference_key"): row for row in project.get("selected_media") or []}
	items = []
	seen = {}
	for kind, rows in (
		("Character", variant.get("pose_views") or []),
		("Product", variant.get("product_views") or []),
		("Product cutout", variant.get("product_cutouts") or []),
	):
		for row in rows:
			key = (
				row.get("view")
				if kind == "Character" and row.get("status") == "ready"
				else (row.get("candidate") if kind == "Product" else row.get("cutout"))
			)
			media = selected.get(key)
			url = frappe.db.get_value("Asset Version", media.asset_version, "file") if media else None
			identity = (kind, key or row.get("source"), row.get("pose") or row.get("view"), row.get("status"))
			if identity in seen:
				if row.get("scene") and row["scene"] not in seen[identity]["scenes"]:
					seen[identity]["scenes"].append(row["scene"])
				continue
			item = {
				"kind": kind,
				"scenes": [row["scene"]] if row.get("scene") else [],
				"description": row.get("pose") if kind == "Character" else row.get("view"),
				"status": row.get("status"),
				"reference_key": key if media else None,
				"url": url if row.get("status") == "ready" else None,
			}
			seen[identity] = item
			items.append(item)
	return items


@frappe.whitelist()
def get_product_batch(batch_name):
	batch = frappe.get_doc("Creative Batch", batch_name)
	batch.check_permission("read")
	variants = frappe.parse_json(batch.variants_json or "[]")
	request = frappe.parse_json(batch.request_json or "{}")
	for variant in variants:
		variant["prepared_assets"] = _prepared_assets(variant)
		# The name read from the package as the project shows it; the script's is the English production name.
		variant["product"] = (
			frappe.db.get_value("Media Project", variant["project"], "product_name")
			if variant.get("project")
			else None
		) or (variant.get("script") or {}).get("product_name")
		if (
			variant.get("status") == "Needs Attention"
			and variant.get("resume_stage") == "Rendering"
			and variant.get("project")
		):
			from joymedia.services.generation.creative_batch import held_scene_clips

			variant["held_clips"] = held_scene_clips(variant["project"])
		if variant.get("script") and variant.get("project"):
			from joymedia.services.generation.creative_batch import _unprotected
			from joymedia.services.keyframes.stage import get_project_keyframes

			notes = variant.get("picture_notes") or {}
			variant["pictures"] = [
				{
					**row,
					"note": (
						row.get("review_notes")
						if row.get("review_status") in {"Needs Review", "Redrawing", "Checking"}
						and str(row.get("review_notes") or "").startswith("Critical ")
						else notes.get(row["shot"], "")
					)
					if row.get("url")
					else (
						_missing_picture_reason(row["shot"])
						if variant.get("status") in {"Pictures Ready", "Needs Attention"}
						else notes.get(row["shot"], "")
					),
					"label_unlocked": _unprotected(frappe.get_doc("Shot", row["shot"])),
				}
				for row in get_project_keyframes(variant["project"])
			]
		if variant.get("project"):
			# A progressive rough cut is meaningful only when its scene list makes
			# clear which parts are live clips and which are storyboard holds.
			clips = dict(
				frappe.get_all(
					"Asset Version",
					filters={
						"name": [
							"in",
							frappe.get_all(
								"Shot",
								filters={"media_project": variant["project"], "is_removed": 0},
								pluck="selected_output_asset_version",
							),
						]
					},
					fields=["name", "file"],
					as_list=True,
				)
			)
			# Each scene's own clip, so a reviewer can judge and remake scenes one by one.
			variant["preview_scenes"] = [
				{
					"shot": row.name,
					"shot_name": row.shot_name,
					"shot_number": row.shot_number,
					"ready": bool(row.selected_output_asset_version),
					"clip": clips.get(row.selected_output_asset_version),
					# Repairs ran out: the scene is delivered, but never presented as verified.
					"unresolved": [
						part.strip()
						for part in (row.consistency_notes or "").split("; ")
						if part.strip().startswith("Critical")
					][:2]
					if row.consistency_status == "Needs Review"
					else [],
				}
				for row in frappe.get_all(
					"Shot",
					filters={"media_project": variant["project"], "is_removed": 0},
					fields=[
						"name",
						"shot_name",
						"shot_number",
						"selected_output_asset_version",
						"consistency_status",
						"consistency_notes",
					],
					order_by="shot_number asc, name asc",
				)
			]
	return {
		"name": batch.name,
		"source_project": batch.source_project,
		"status": batch.status,
		"variants": variants,
		"error": batch.error,
		"delivery_mode": request.get("delivery_mode", "assisted"),
	}


def _missing_picture_reason(shot_name):
	"""Why a scene has no picture, from the visual check's own findings, in reviewer terms."""
	from joymedia.services.review.admission import report_for

	failed = frappe.db.sql(
		"""select a.name, a.error_details from `tabGeneration Attempt` a
		join `tabGeneration Task` t on t.name = a.generation_task
		where t.shot = %s and a.status = 'Failed' order by a.creation desc limit 10""",
		shot_name,
		as_dict=True,
	)
	if not failed:
		return ""
	report = report_for(failed[0].name) or {}
	missing = [
		row["claim"]
		for row in report.get("results") or []
		if row.get("verdict") in {"violated", "uncertain"}
		and "independently qualified" not in str(row.get("claim"))
	]
	reason = "; ".join(missing[:3]) or str(failed[0].error_details or "").removeprefix(
		"Reference preparation was rejected. "
	)
	return (
		f"Not drawn after {len(failed)} tries. The check could not confirm: {reason[:300].rstrip('. ')}. "
		"Draw again, or add a note to rewrite this scene."
	)


@frappe.whitelist()
def get_attention():
	"""The user's AI videos that wait for them or are finished, for in-app alerts.

	Light enough to poll: batch rows only, no per-scene work.
	"""
	waiting = {"Pictures Ready", "Script Ready", "Needs Attention"}
	rows, seen = [], set()
	for batch in frappe.get_list(
		"Creative Batch",
		filters={"owner": frappe.session.user, "status": ["!=", "Cancelled"]},
		fields=["variants_json"],
		order_by="modified desc",
		limit_page_length=40,
	):
		for variant in frappe.parse_json(batch.variants_json or "[]"):
			project = variant.get("project")
			if not project or project in seen or variant.get("status") not in waiting | {"Completed"}:
				continue
			seen.add(project)
			if frappe.db.get_value("Media Project", project, "status") == "Archived":
				continue
			rows.append(
				{
					"project": project,
					"title": (variant.get("script") or {}).get("display_title")
					or variant.get("title")
					or (variant.get("script") or {}).get("title")
					or "",
					"state": "ready" if variant["status"] == "Completed" else "waiting",
				}
			)
	return rows


@frappe.whitelist()
def get_project_batches(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	from joymedia.services.project.versions import family, members

	project_family = members(family(project))
	return [
		get_product_batch(name)
		for name in frappe.get_all(
			"Creative Batch",
			filters={"source_project": ["in", project_family], "owner": project.owner},
			pluck="name",
			order_by="creation desc",
			limit=10,
		)
	]


@frappe.whitelist(methods=["POST"])
def cancel_product_batch(batch_name):
	batch = frappe.get_doc("Creative Batch", batch_name)
	batch.check_permission("write")
	with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
		frappe.db.set_value("Creative Batch", batch.name, "status", "Cancelled")
		frappe.db.commit()  # Durable cancellation precedes interrupting any native jobs.
		batch.reload()
	from joymedia.api.projects import cancel_project_generation
	from joymedia.services.editing.post_production import cancel_post_production

	for variant in frappe.parse_json(batch.variants_json or "[]"):
		if not variant.get("project"):
			continue
		cancel_project_generation(variant["project"])
		if frappe.db.get_value("Media Project", variant["project"], "post_production_status") in {
			"Queued",
			"Running",
		}:
			cancel_post_production(variant["project"])
	return {"batch": batch.name, "status": "Cancelled"}


@frappe.whitelist(methods=["POST"])
def retry_product_variant(batch_name, index):
	"""Resume a stopped variant through its native stage, retaining prior evidence."""
	batch = frappe.get_doc("Creative Batch", batch_name)
	batch.check_permission("write")
	if type(index) is bool or str(index) not in {str(i) for i in range(1, 21)}:
		raise ValueError("Choose a variant number from one to twenty.")
	with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		batch.reload()
		if batch.status == "Cancelled":
			raise ValueError("A cancelled batch cannot be resumed.")
		variants = frappe.parse_json(batch.variants_json)
		position = int(index) - 1
		if position >= len(variants) or variants[position]["status"] != "Needs Attention":
			raise ValueError("Only a stopped variant can be retried.")
		variant = variants[position]
		stage = variant.get("resume_stage", "Planning")
		if stage not in {"Planning", "Locations", "Keyframes", "Rendering", "Finishing", "Exporting"}:
			raise ValueError("The stopped stage is not resumable.")
		if stage == "Locations":
			# Planning is already persisted; the normal preparer reuses the script
			# and workbook, then queues only the missing shared-setting work.
			stage = "Planning"
		if stage == "Keyframes" and variant.get("project"):
			# This is a fresh recovery request, often after the prompt/compiler or a
			# workflow configuration has been corrected.  Do not let the old bounded
			# stochastic attempts immediately re-raise the same exhausted-retries
			# error.  Keep all recorded attempt evidence, but give only the currently
			# missing frames a new bounded retry budget.
			missing = set(
				frappe.get_all(
					"Shot",
					filters={
						"media_project": variant["project"],
						"is_removed": 0,
						"keyframe_artifact": ["is", "not set"],
					},
					pluck="name",
				)
			)
			if missing:
				variant["auto_redraws"] = [
					name for name in (variant.get("auto_redraws") or []) if name not in missing
				]
				variant.setdefault("recovery_events", []).append(
					{
						"stage": "Keyframes",
						"shots": sorted(missing),
						"reason": "Explicit recovery starts a fresh bounded first-frame retry budget.",
					}
				)
		if stage == "Rendering" and variant.get("project"):
			from joymedia.services.generation.creative_batch import rerender_failed_scenes

			# Re-reading the failed run would stop again: render new takes of the
			# scenes that have none, keeping every finished take and approved picture.
			rerender_failed_scenes(variant, frappe.parse_json(batch.request_json))
		if stage == "Planning" and not variant.get("script"):
			# Explicit recovery receives a fresh bounded image-analysis retry budget.
			variant.pop("reference_analysis_attempts", None)
			# An unchanged variation ID retrieves the same cached rejected draft.
			# Keep the failed proposal's identity and reason, then ask for a new
			# concept. Accepted scripts/workbooks and media retries remain stable.
			variant.setdefault("script_attempts", []).append(
				{"nonce": variant.get("nonce"), "error": variant.get("error", "")}
			)
			variant["nonce"] = uuid.uuid4().hex
		variant.update(status=stage, error="")
		frappe.db.set_value(
			"Creative Batch",
			batch.name,
			{
				"variants_json": frappe.as_json(variants),
				"error": "",
				"status": "Planning"
				if stage == "Planning"
				else "Rendering"
				if stage in {"Locations", "Keyframes", "Rendering"}
				else "Finishing",
			},
		)
		from joymedia.services.generation.creative_batch import _planning_queue

		frappe.enqueue(
			"joymedia.services.generation.creative_batch.prepare_batch"
			if stage == "Planning"
			else "joymedia.services.generation.creative_batch.advance_batch",
			queue="long" if stage != "Planning" or variant.get("script") else _planning_queue(),
			timeout=3600,
			batch_name=batch.name,
			**({"position": position} if stage == "Planning" else {}),
			job_id=(
				f"joymedia-creative-prepare:{batch.name}:{position}"
				if stage == "Planning"
				else f"joymedia-creative-advance:{batch.name}"
			),
			deduplicate=True,
			enqueue_after_commit=True,
		)
		frappe.db.commit()
	return {"batch": batch.name, "index": int(index), "status": stage}


@frappe.whitelist(methods=["POST"])
def revise_product_variant(batch_name, index, notes):
	"""Ask the AI to rewrite one script from the reviewer's notes before any video is made.

	notes: list of {"scene": scene number or null for the whole script, "text": note}.
	"""
	from joymedia.services.generation.creative_batch import revise_variant

	batch = frappe.get_doc("Creative Batch", batch_name)
	batch.check_permission("write")
	if type(index) is bool or str(index) not in {str(i) for i in range(1, 21)}:
		raise ValueError("Choose a variant number from one to twenty.")
	notes = frappe.parse_json(notes) if isinstance(notes, str) else notes
	if (
		not isinstance(notes, list)
		or not 1 <= len(notes) <= 30
		or any(
			not isinstance(n, dict)
			or not str(n.get("text") or "").strip()
			or len(str(n["text"])) > 1000
			or (n.get("scene") is not None and (type(n["scene"]) is not int or not 1 <= n["scene"] <= 12))
			for n in notes
		)
	):
		raise ValueError("Write one to thirty notes, each up to 1000 characters.")
	notes = [{"scene": n.get("scene"), "text": str(n["text"]).strip()} for n in notes]
	return revise_variant(batch.name, int(index) - 1, notes)


def _variant_position(batch_name, index):
	batch = frappe.get_doc("Creative Batch", batch_name)
	batch.check_permission("write")
	if type(index) is bool or str(index) not in {str(i) for i in range(1, 21)}:
		raise ValueError("Choose a variant number from one to twenty.")
	return batch.name, int(index) - 1


@frappe.whitelist(methods=["POST"])
def approve_variant_pictures(batch_name, index):
	"""Approve every scene picture of one video and make the video."""
	from joymedia.services.generation.creative_batch import approve_variant_pictures as approve

	return approve(*_variant_position(batch_name, index))


@frappe.whitelist(methods=["POST"])
def accept_held_clip(batch_name, index, shot_name, note, attempt_name=None, asset_version=None):
	"""Use a clip the automatic check could not qualify, after a person watched it."""
	from joymedia.services.generation.creative_batch import accept_held_clip as accept

	if not isinstance(note, str) or not note.strip():
		raise ValueError("Say what you checked in this clip.")
	if not attempt_name and not asset_version:
		raise ValueError("Choose the clip to use.")
	return accept(
		*_variant_position(batch_name, index),
		shot_name,
		note.strip(),
		attempt_name=attempt_name,
		asset_version=asset_version,
	)


@frappe.whitelist(methods=["POST"])
def redraw_variant_picture(batch_name, index, shot_name):
	"""Draw one scene picture of one video again."""
	from joymedia.services.generation.creative_batch import redraw_variant_picture as redraw

	return redraw(*_variant_position(batch_name, index), shot_name)


@frappe.whitelist(methods=["POST"])
def retry_variant_scene_with_prompt(batch_name, index, shot_name, instruction=""):
	"""Regenerate one completed scene with an optional, human-directed prompt change.

	This is deliberately a scene operation: all other selected takes remain in the
	working cut.  The batch scheduler then replaces only this take and rebuilds
	the progressive preview and final export without asking for a second approval.
	"""
	from joymedia.services.generation.creative_batch import retry_variant_scene_with_prompt as retry

	instruction = str(instruction or "").strip()
	if len(instruction) > 2000:
		raise ValueError("Keep a scene instruction under 2000 characters.")
	return retry(*_variant_position(batch_name, index), shot_name, instruction)


@frappe.whitelist(methods=["POST"])
def render_product_variant(batch_name, index):
	"""The reviewer approved a written script: continue that video through rendering."""
	from joymedia.services.generation.creative_batch import start_variant_render

	batch = frappe.get_doc("Creative Batch", batch_name)
	batch.check_permission("write")
	if type(index) is bool or str(index) not in {str(i) for i in range(1, 21)}:
		raise ValueError("Choose a variant number from one to twenty.")
	return start_variant_render(batch.name, int(index) - 1)
