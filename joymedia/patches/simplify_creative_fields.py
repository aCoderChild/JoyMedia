import frappe


LEGACY_SHOT_FIELDS = (
	("shot_instructions", "Shot Instructions"),
	("subject_identity", "Subject"),
	("action_plot", "Action / Motion"),
	("camera_direction", "Camera"),
	("environment", "Environment / Lighting"),
	("audio_direction", "Audio"),
)


def execute():
	_merge_media_specification_instructions()
	_backfill_shot_generation_prompts()


def _merge_media_specification_instructions():
	"""Preserve legacy project-wide creative text in global_instructions."""
	if not frappe.db.has_column("Media Specification", "global_instructions"):
		return
	legacy_fields = [
		fieldname
		for fieldname in ("global_consistency_instructions", "generation_instructions")
		if frappe.db.has_column("Media Specification", fieldname)
	]
	if not legacy_fields:
		return
	columns = ", ".join(["name", "global_instructions"] + legacy_fields)
	rows = frappe.db.sql(f"SELECT {columns} FROM `tabMedia Specification`", as_dict=True)
	for row in rows:
		parts = []
		for value in [row.global_instructions] + [row.get(fieldname) for fieldname in legacy_fields]:
			text = str(value or "").strip()
			if text and text not in parts:
				parts.append(text)
		if parts:
			frappe.db.set_value(
				"Media Specification", row.name, "global_instructions", "\n\n".join(parts), update_modified=False
			)


def _backfill_shot_generation_prompts():
	"""Preserve old structured shot direction when a canonical prompt is missing."""
	if not frappe.db.has_column("Shot Specification", "generation_prompt"):
		return
	available = [
		(fieldname, label)
		for fieldname, label in LEGACY_SHOT_FIELDS
		if frappe.db.has_column("Shot Specification", fieldname)
	]
	if not available:
		return
	columns = ", ".join(["name", "generation_prompt"] + [fieldname for fieldname, _ in available])
	rows = frappe.db.sql(f"SELECT {columns} FROM `tabShot Specification`", as_dict=True)
	for row in rows:
		if str(row.generation_prompt or "").strip():
			continue
		parts = []
		for fieldname, label in available:
			value = str(row.get(fieldname) or "").strip()
			if value:
				parts.append(f"{label}: {value}")
		if parts:
			frappe.db.set_value(
				"Shot Specification", row.name, "generation_prompt", "\n".join(parts), update_modified=False
			)
