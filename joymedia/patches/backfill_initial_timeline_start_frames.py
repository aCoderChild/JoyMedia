import frappe


def execute():
	for clip in frappe.get_all(
		"Timeline Clip",
		fields=["name", "timeline_start_frame"],
	):
		frappe.db.set_value(
			"Timeline Clip",
			clip.name,
			"initial_timeline_start_frame",
			int(clip.timeline_start_frame or 0),
			update_modified=False,
		)
