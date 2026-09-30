"""Frame-exact planning for Shot Specifications within a Media Specification."""

import frappe
from frappe import _


def rebalance_shot_duration(media_specification_name: str, shot_name: str, target_duration_seconds: float):
	"""Change one shot while keeping the specification's canonical duration fixed."""
	media_specification = frappe.get_doc("Media Specification", media_specification_name)
	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_specification.name},
		fields=["name", "shot_number", "duration_seconds"],
		order_by="shot_number asc, name asc",
	)
	if not shots:
		frappe.throw(_("The Media Specification has no Shot Specifications."))
	if not media_specification.workflow:
		frappe.throw(_("Media Specification must have a Workflow."))
	workflow_version = frappe.get_doc("Workflow", media_specification.workflow)
	fps = float(workflow_version.output_fps or 0)
	if fps <= 0:
		frappe.throw(_("Workflow output FPS must be greater than zero."))

	total_frames = round(float(media_specification.total_duration_seconds or 0) * fps)
	if total_frames < len(shots):
		frappe.throw(_("Total Duration must provide at least one frame for each Shot Specification."))
	target = next((index for index, row in enumerate(shots) if row.name == shot_name), None)
	if target is None:
		frappe.throw(_("Shot does not belong to this Media Specification."))
	target_frames = max(1, min(round(float(target_duration_seconds) * fps), total_frames - len(shots) + 1))
	remaining_frames = total_frames - target_frames
	other_indexes = [index for index in range(len(shots)) if index != target]
	if not other_indexes:
		planned_frames = [target_frames]
	else:
		weights = [max(1.0, float(shots[index].duration_seconds or 0) * fps) for index in other_indexes]
		weight_total = sum(weights)
		raw = [remaining_frames * weight / weight_total for weight in weights]
		planned_other = [max(1, int(value)) for value in raw]
		left = remaining_frames - sum(planned_other)
		order = sorted(range(len(raw)), key=lambda index: raw[index] - int(raw[index]), reverse=True)
		for index in order:
			if left <= 0:
				break
			planned_other[index] += 1
			left -= 1
		planned_frames = [0] * len(shots)
		planned_frames[target] = target_frames
		for index, shot_index in enumerate(other_indexes):
			planned_frames[shot_index] = planned_other[index]

	for shot, planned_frame_count in zip(shots, planned_frames):
		frappe.db.set_value(
			"Shot Specification",
			shot.name,
			{
				"planned_frame_count": planned_frame_count,
				"duration_seconds": planned_frame_count / fps,
			},
			update_modified=False,
		)
	return {
		"total_duration_seconds": total_frames / fps,
		"shots": len(shots),
		"duration_seconds": planned_frames[target] / fps,
	}


def recalculate_shot_durations(media_specification_name: str):
	"""Distribute a specification's intended duration across its shots in whole frames.

	The earliest shots receive any remainder frames so the planned shot timeline always
	sums exactly to the Media Specification's total frame count.
	"""
	media_specification = frappe.get_doc("Media Specification", media_specification_name)
	shots = frappe.get_all(
		"Shot Specification",
		filters={"media_specification": media_specification.name},
		fields=["name", "shot_number", "duration_seconds"],
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
	existing_durations = [float(shot.duration_seconds or 0) for shot in shots]
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
