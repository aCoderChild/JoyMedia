import frappe


def execute():
	"""Backfill the canonical shot prompt without changing legacy source fields."""
	if not frappe.db.table_exists("Shot Specification"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, generation_prompt, shot_instructions,
			camera_direction, subject_identity, action_plot,
			environment, audio_direction
		FROM `tabShot Specification`
		WHERE generation_prompt IS NULL OR generation_prompt = ''
		""",
		as_dict=True,
	)
	for row in rows:
		prompt = (row.shot_instructions or "").strip()
		if not prompt:
			prompt = "\n".join(
				line
				for label, value in (
					("Subject", row.subject_identity),
					("Action / Motion", row.action_plot),
					("Camera", row.camera_direction),
					("Environment", row.environment),
					("Audio", row.audio_direction),
				)
				if (line := f"{label}: {value or ''}").split(": ", 1)[1].strip()
			)
		if prompt:
			frappe.db.set_value(
				"Shot Specification", row.name, "generation_prompt", prompt, update_modified=False
			)
