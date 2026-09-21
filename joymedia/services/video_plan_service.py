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

	shot_numbers = [shot["shot_number"] for shot in plan["shots"]]
	if len(shot_numbers) != len(set(shot_numbers)):
		frappe.throw(_("Video plan contains duplicate shot numbers."))

	reference_image_indexes = {
		shot["reference_image_index"] for shot in plan["shots"] if "reference_image_index" in shot
	}
	asset_version_by_index = {}
	required_input_role = None
	if reference_image_indexes:
		from joymedia.services.project_image_manifest import get_project_image_manifest

		image_manifest = get_project_image_manifest(media_spec.media_project)
		asset_version_by_index = {image["index"]: image["asset_version"] for image in image_manifest}
		if not media_spec.generation_workflow_version:
			frappe.throw(_("The Media Specification requires a Generation Workflow Version."))

		workflow_version = frappe.get_doc("Workflow Version", media_spec.generation_workflow_version)
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
			}
		)
		reference_image_index = shot.get("reference_image_index")
		resolved_asset_version = None
		if reference_image_index is not None:
			resolved_asset_version = asset_version_by_index.get(reference_image_index)
			if not resolved_asset_version:
				frappe.throw(
					_("Reference image index {0} could not be resolved.").format(reference_image_index)
				)

		if resolved_asset_version:
			if not required_input_role:
				frappe.throw(_("The Media Specification workflow has no required Generation Input role."))
			doc.append(
				"generation_inputs",
				{
					"input_role": required_input_role,
					"asset_version": resolved_asset_version,
				},
			)
		doc.insert(ignore_permissions=True)
		created_shots.append(doc.name)

	return created_shots
