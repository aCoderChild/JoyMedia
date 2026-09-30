import frappe


def execute():
	profile = frappe.db.get_value("AI Model Profile", {"model_key": "joymedia-qwen"}, "name")
	if not profile:
		profile = frappe.get_doc(
			{
				"doctype": "AI Model Profile",
				"model_name": "JoyMedia Qwen",
				"model_key": "joymedia-qwen",
				"model_family": "Qwen2.5",
				"capability": "Text prompt generation",
				"adapter_key": "minimax_h3",
				"enabled": 1,
				"production_approved": 1,
			}
		).insert(ignore_permissions=True).name

	for workflow_name in frappe.get_all("Generation Workflow", pluck="name"):
		if not frappe.db.get_value("Generation Workflow", workflow_name, "ai_model_profile"):
			frappe.db.set_value(
				"Generation Workflow", workflow_name, "ai_model_profile", profile, update_modified=False
			)

	endpoint_url = frappe.conf.get("comfyui_base_url")
	if endpoint_url and not frappe.db.exists("Generation Backend", {"endpoint_url": endpoint_url}):
		frappe.get_doc(
			{
				"doctype": "Generation Backend",
				"backend_name": "Default ComfyUI",
				"backend_type": "ComfyUI",
				"endpoint_url": endpoint_url,
				"enabled": 1,
				"status": "Unknown",
			}
		).insert(ignore_permissions=True)
