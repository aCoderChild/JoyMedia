import frappe


def execute():
	profile = frappe.db.get_value("AI Model Profile", {"model_key": "minimax-h3"}, "name")
	if not profile:
		profile = frappe.get_doc(
			{
				"doctype": "AI Model Profile",
				"model_name": "MiniMax H3",
				"model_key": "minimax-h3",
				"model_family": "MiniMax H3",
				"capability": "Image to video",
				"adapter_key": "minimax_h3",
				"enabled": 1,
				"production_approved": 1,
				"supports_image_to_video": 1,
				"supports_first_frame": 1,
				"supports_last_frame": 1,
				"supports_audio": 1,
			}
		).insert(ignore_permissions=True).name

	for workflow_name in frappe.get_all("Generation Workflow", pluck="name"):
		frappe.db.set_value(
			"Generation Workflow", workflow_name, "ai_model_profile", profile, update_modified=False
		)
