import json

import frappe
from frappe import _


@frappe.whitelist()
def apply_video_plan_from_ui(media_specification_name: str, plan_json: str):
	frappe.has_permission(
		"Media Specification",
		"write",
		media_specification_name,
		throw=True,
	)

	plan = parse_video_plan(plan_json)

	created_shots = apply_video_plan(
		media_specification_name=media_specification_name,
		plan=plan,
	)

	frappe.db.commit()

	return {
		"media_specification": media_specification_name,
		"shots": created_shots,
	}


def parse_video_plan(plan_json: str):
	try:
		return json.loads(plan_json)
	except (TypeError, ValueError, json.JSONDecodeError):
		frappe.throw(_("Invalid video plan JSON."))


def apply_video_plan(media_specification_name: str, plan: dict):
	media_spec = frappe.get_doc("Media Specification", media_specification_name)

	if media_spec.status != "Draft":
		frappe.throw(_("Video plans can only be applied to Draft Media Specifications."))
	mode = {"Independent": "Multi-shot", "Chained": "Continuous", "Consistency": "Continuous"}.get(
		media_spec.continuity_mode, media_spec.continuity_mode or "Multi-shot"
	)
	if mode not in ("Multi-shot", "Continuous"):
		frappe.throw(_("Select Continuous or Multi-shot generation mode."))
	uses_keyframe_fields = any(
		fieldname in shot
		for shot in plan["shots"]
		for fieldname in ("first_frame_reference_image_index", "last_frame_reference_image_index")
	)

	shot_numbers = [shot["shot_number"] for shot in plan["shots"]]
	if len(shot_numbers) != len(set(shot_numbers)):
		frappe.throw(_("Video plan contains duplicate shot numbers."))

	reference_image_indexes = set()
	for shot in plan["shots"]:
		for fieldname in (
			"reference_image_index",
			"first_frame_reference_image_index",
			"last_frame_reference_image_index",
		):
			if shot.get(fieldname) is not None:
				reference_image_indexes.add(shot[fieldname])
	asset_version_by_index = {}
	required_input_role = None
	if reference_image_indexes:
		from joymedia.services.project_image_manifest import get_project_image_manifest

		image_manifest = get_project_image_manifest(media_spec.media_project)
		asset_version_by_index = {image["index"]: image["asset_version"] for image in image_manifest}
		if not media_spec.workflow:
			frappe.throw(_("The Media Specification requires a Workflow."))

		workflow_version = frappe.get_doc("Workflow", media_spec.workflow)
		required_input_roles = {
			frappe.scrub(binding.required_input_role)
			for binding in workflow_version.bindings
			if binding.value_source == "Generation Input"
			and binding.required
			and binding.required_input_role
		}
		if len(required_input_roles) > 1:
			frappe.throw(
				_("Video plan application requires exactly one required Generation Input role.")
			)
		required_input_role = next(iter(required_input_roles), None)

	existing_shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_spec.name},
		pluck="name",
	)
	if existing_shots:
		if frappe.db.exists("Generation Run", {"media_specification": media_spec.name}):
			frappe.throw(
				_(
					"This storyboard cannot be replaced after generation starts. "
					"Create a new revision instead."
				)
			)

		for shot_name in existing_shots:
			frappe.delete_doc("Shot Specification", shot_name, ignore_permissions=True)

	created_shots = []
	resolved_shot_inputs = []
	shot_docs = []

	for shot in plan["shots"]:
		doc = frappe.get_doc(
			{
				"doctype": "Shot Specification",
				"media_specification": media_spec.name,
				"shot_number": shot["shot_number"],
				"camera_direction": shot["camera"],
				"subject_identity": shot["subject"],
				"action_plot": shot["motion"],
				"environment": shot["lighting"],
				"audio_direction": shot["audio"],
				"generation_prompt": shot.get("generation_prompt") or _fallback_generation_prompt(shot),
			}
		)
		first_reference_index = shot.get("first_frame_reference_image_index")
		if first_reference_index is None:
			first_reference_index = shot.get("reference_image_index")
		last_reference_index = shot.get("last_frame_reference_image_index")
		first_asset_version = asset_version_by_index.get(first_reference_index)
		last_asset_version = asset_version_by_index.get(last_reference_index)
		if first_reference_index is not None and not first_asset_version:
			frappe.throw(
				_("First-frame reference image index {0} could not be resolved.").format(
					first_reference_index
				)
			)
		if last_reference_index is not None and not last_asset_version:
			frappe.throw(
				_("Last-frame reference image index {0} could not be resolved.").format(
					last_reference_index
				)
			)

		if mode == "Multi-shot" and uses_keyframe_fields and reference_image_indexes and (
			first_asset_version is None or last_asset_version is None
		):
			frappe.throw(
				_("Multi-shot requires first-frame and last-frame references for every shot.")
			)

		if first_asset_version and (mode == "Multi-shot" or shot["shot_number"] == 1):
			if not required_input_role:
				frappe.throw(_("The Media Specification workflow has no required Generation Input role."))
			doc.append(
				"generation_inputs",
				{
					"input_role": required_input_role,
					"asset_version": first_asset_version,
				},
			)
		if mode == "Multi-shot" and last_asset_version:
			doc.append(
				"generation_inputs",
				{
					"input_role": "last_frame",
					"asset_version": last_asset_version,
				},
			)
		resolved_shot_inputs.append(
			{
				"shot_number": shot["shot_number"],
				"first_frame": first_asset_version,
				"last_frame": last_asset_version,
			}
		)
		shot_docs.append(doc)

	if mode == "Multi-shot" and uses_keyframe_fields:
		resolved_shot_inputs.sort(key=lambda item: item["shot_number"])
		for current, following in zip(resolved_shot_inputs, resolved_shot_inputs[1:]):
			if current["last_frame"] != following["first_frame"]:
				frappe.throw(
					_("Multi-shot boundary is invalid between shots {0} and {1}.").format(
						current["shot_number"], following["shot_number"]
					)
				)

	for doc in shot_docs:
		doc.insert(ignore_permissions=True)
		created_shots.append(doc.name)

	return created_shots


def _fallback_generation_prompt(shot):
	return "\n".join(
		line
		for line in (
			f"Camera & Framing: {shot.get('camera', '')}",
			f"Subject: {shot.get('subject', '')}",
			f"Motion: {shot.get('motion', '')}",
			f"Lighting & Environment: {shot.get('lighting', '')}",
			f"Audio: {shot.get('audio', '')}",
		)
		if line.split(": ", 1)[1].strip()
	)
