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
	"""Preserve the old generation text inside the one surviving global field."""
	if not frappe.db.has_column("Media Specification", "global_consistency_instructions"):
		return
	if not frappe.db.has_column("Media Specification", "generation_instructions"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, generation_instructions, global_consistency_instructions
		FROM `tabMedia Specification`
		""",
		as_dict=True,
	)
	for row in rows:
		legacy = str(row.generation_instructions or "").strip()
		current = str(row.global_consistency_instructions or "").strip()
		if not legacy:
			continue
		if not current:
			merged = legacy
		elif legacy == current or legacy in current:
			merged = current
		else:
			merged = f"{current}\n\n{legacy}"
		if merged != current:
			frappe.db.set_value(
				"Media Specification",
				row.name,
				"global_consistency_instructions",
				merged,
				update_modified=False,
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
	rows = frappe.db.sql(
		f"SELECT {columns} FROM `tabShot Specification`",
		as_dict=True,
	)
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
				"Shot Specification",
				row.name,
				"generation_prompt",
				"\n".join(parts),
				update_modified=False,
			)
