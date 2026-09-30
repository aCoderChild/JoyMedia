import frappe


def execute():
	if not frappe.db.table_exists("Shot Specification"):
		return
	q = chr(96)
	rows = frappe.db.sql(
		f"""
		SELECT name, camera_direction, subject_identity, action_plot,
			environment, audio_direction, generation_prompt
		FROM {q}tabShot Specification{q}
		WHERE shot_instructions IS NULL OR shot_instructions = ''
		""",
		as_dict=True,
	)
	for row in rows:
		parts = [
			("Subject", row.subject_identity),
			("Action / Motion", row.action_plot),
			("Camera", row.camera_direction),
			("Environment", row.environment),
			("Audio", row.audio_direction),
			("Existing Prompt", row.generation_prompt),
		]
		instructions = "\n".join(
			f"{label}: {value.strip()}" for label, value in parts if value and value.strip()
		)
		if instructions:
			frappe.db.set_value(
				"Shot Specification", row.name, "shot_instructions", instructions, update_modified=False
			)
