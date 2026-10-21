"""Product-reference automation entry points, shared by browser and integrations."""

import math
import uuid

import frappe


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
):
	from joymedia.services.intake.references import brand, preservation_modes
	from joymedia.services.project.formats import delivery_dimensions, orientation, parse_ratio, ratio_label

	project = frappe.get_doc("Media Project", source_project)
	project._require_write_access()
	from joymedia.services.partners import is_reviewer, require_generation

	if is_reviewer():
		require_generation()
	if type(count) is bool or str(count) not in {str(i) for i in range(1, 21)}:
		raise ValueError("Choose one to twenty video variants.")
	count = int(count)
	keys = frappe.parse_json(reference_keys) if isinstance(reference_keys, str) else reference_keys
	if keys is not None and (not isinstance(keys, list) or any(not isinstance(k, str) for k in keys)):
		raise ValueError("Reference keys must be a list.")
	allowed = {"Product", "Character", "Person", "Logo", "Environment", "Motion", "Style"}
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
		"auto_render": str(auto_render).lower() in {"1", "true", "yes", "on"},
		"direction": direction or "",
		"duration_seconds": duration or None,
		"width": width,
		"height": height,
		"delivery_preset": orientation(ratio) if ratio else None,
		"product_name": project.product_name or "",
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
	variants = [{"index": i + 1, "status": "Queued", "nonce": uuid.uuid4().hex} for i in range(count)]
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
	frappe.enqueue(
		"joymedia.services.generation.creative_batch.prepare_batch",
		queue="long",
		timeout=3600,
		batch_name=batch.name,
		job_id=f"joymedia-creative-prepare:{batch.name}:0",
		deduplicate=True,
		enqueue_after_commit=True,
	)
	return {"batch": batch.name, "status": "Queued", "count": count}


@frappe.whitelist()
def get_product_batch(batch_name):
	batch = frappe.get_doc("Creative Batch", batch_name)
	batch.check_permission("read")
	return {
		"name": batch.name,
		"source_project": batch.source_project,
		"status": batch.status,
		"variants": frappe.parse_json(batch.variants_json or "[]"),
		"error": batch.error,
	}


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
		frappe.enqueue(
			"joymedia.services.generation.creative_batch.prepare_batch"
			if stage == "Planning"
			else "joymedia.services.generation.creative_batch.advance_batch",
			queue="long",
			timeout=3600,
			batch_name=batch.name,
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
