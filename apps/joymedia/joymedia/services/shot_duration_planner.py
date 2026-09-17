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

	fps = float(media_specification.target_fps or 0)
	if fps <= 0:
		frappe.throw(_("Media Specification Target FPS must be greater than zero."))

	total_frames = round(float(media_specification.total_duration_seconds or 0) * fps)
	if total_frames < len(shots):
		frappe.throw(
			_("Total Duration must provide at least one frame for each Shot Specification.")
		)

	base_frames, remainder = divmod(total_frames, len(shots))
	for index, shot in enumerate(shots):
		planned_frame_count = base_frames + (1 if index < remainder else 0)
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
