"""Backfill technical segment boundaries without changing task prompts or attempts."""

import frappe


def execute():
	for group in frappe.db.sql(
		"""
		select generation_run, shot
		from `tabGeneration Task`
		where ifnull(segment_effective_frames, 0) = 0
		group by generation_run, shot
		""",
		as_dict=True,
	):
		cursor = 0
		rows = frappe.get_all(
			"Generation Task",
			filters={"generation_run": group.generation_run, "shot": group.shot},
			fields=["name", "segment_index", "segment_frame_count"],
			order_by="segment_index asc, creation asc",
		)
		for row in rows:
			overlap = 0 if int(row.segment_index or 1) == 1 else 1
			frame_count = int(row.segment_frame_count or 0)
			effective = max(1, frame_count - overlap)
			frappe.db.set_value(
				"Generation Task",
				row.name,
				{
					"segment_start_frame": cursor,
					"segment_effective_frames": effective,
					"overlap_frames": overlap,
				},
				update_modified=False,
			)
			cursor += effective
