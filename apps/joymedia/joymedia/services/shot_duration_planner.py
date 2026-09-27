"""Frame-exact planning for Shot Specifications within a Media Specification."""

import frappe
from frappe import _


def recalculate_shot_durations(media_specification_name: str):
	"""Distribute a specification's intended duration across its shots in whole frames.

	The earliest shots receive any remainder frames so the planned shot timeline always
	sums exactly to the Media Specification's total frame count.
	"""
	media_specification = frappe.get_doc("Media Specification", media_specification_name)
	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_specification.name},
		fields=["name", "shot_number"],
		order_by="shot_number asc, name asc",
	)
	if not shots:
		return {"total_frames": 0, "shots": 0}

	if not media_specification.workflow:
		frappe.throw(_("Media Specification must have a Workflow."))
	workflow_version = frappe.get_doc(
		"Workflow",
		media_specification.workflow,
	)
	fps = float(workflow_version.output_fps or 0)
	if fps <= 0:
		frappe.throw(_("Workflow output FPS must be greater than zero."))

	total_frames = round(float(media_specification.total_duration_seconds or 0) * fps)
	if total_frames < len(shots):
		frappe.throw(
			_("Total Duration must provide at least one frame for each Shot Specification.")
		)

	# Preserve an editor-authored timing split when every shot already has a
	# positive duration. Newly-created storyboards start at zero and therefore
	# still receive the deterministic equal split below.
	existing_durations = [float(frappe.db.get_value("Shot Specification", shot.name, "duration_seconds") or 0) for shot in shots]
	if all(duration > 0 for duration in existing_durations):
		duration_total = sum(existing_durations)
		if duration_total > 0:
			raw_frames = [total_frames * duration / duration_total for duration in existing_durations]
			planned_frames = [max(1, int(value)) for value in raw_frames]
			remaining = total_frames - sum(planned_frames)
			order = sorted(range(len(shots)), key=lambda index: raw_frames[index] - int(raw_frames[index]), reverse=True)
			if remaining > 0:
				for index in order[:remaining]:
					planned_frames[index] += 1
			elif remaining < 0:
				for index in reversed(order):
					if remaining == 0:
						break
					if planned_frames[index] > 1:
						planned_frames[index] -= 1
						remaining += 1
		else:
			planned_frames = []
	else:
		planned_frames = []

	if not planned_frames:
		base_frames, remainder = divmod(total_frames, len(shots))
		planned_frames = [base_frames + (1 if index < remainder else 0) for index in range(len(shots))]

	for index, shot in enumerate(shots):
		planned_frame_count = planned_frames[index]
		frappe.db.set_value(
			"Shot Specification",
			shot.name,
			{
				"planned_frame_count": planned_frame_count,
				"duration_seconds": planned_frame_count / fps,
			},
			update_modified=False,
		)

	return {"total_frames": total_frames, "shots": len(shots)}
