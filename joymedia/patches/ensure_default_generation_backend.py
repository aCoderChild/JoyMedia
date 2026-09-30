import frappe


def execute():
	endpoint_url = frappe.conf.get("comfyui_base_url")
	if not endpoint_url or frappe.db.exists("Generation Backend", {"endpoint_url": endpoint_url}):
		return
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
