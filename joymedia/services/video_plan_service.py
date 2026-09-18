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

	try:
		plan = json.loads(plan_json)
	except (TypeError, ValueError, json.JSONDecodeError):
		frappe.throw(_("Invalid video plan JSON."))

	created_shots = apply_video_plan(
		media_specification_name=media_specification_name,
		plan=plan,
	)

	frappe.db.commit()

	return {
		"media_specification": media_specification_name,
		"shots": created_shots,
	}


def apply_video_plan(media_specification_name: str, plan: dict):
	media_spec = frappe.get_doc("Media Specification", media_specification_name)

	if media_spec.status != "Draft":
		frappe.throw(_("Video plans can only be applied to Draft Media Specifications."))

	existing_shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_spec.name},
		limit=1,
	)
	if existing_shots:
		frappe.throw(
			_("Video plan can only be applied to a Media Specification with no existing shots.")
		)

	shot_numbers = [shot["shot_number"] for shot in plan["shots"]]
	if len(shot_numbers) != len(set(shot_numbers)):
		frappe.throw(_("Video plan contains duplicate shot numbers."))

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
		doc.insert(ignore_permissions=True)
		created_shots.append(doc.name)

	return created_shots
