import frappe
from frappe import _


def apply_video_plan(media_specification_name: str, plan: dict):
	media_spec = frappe.get_doc("Media Specification", media_specification_name)

	if media_spec.status != "Draft":
		frappe.throw(_("Video plans can only be applied to Draft Media Specifications."))

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
		doc.insert()
		created_shots.append(doc.name)

	return created_shots
