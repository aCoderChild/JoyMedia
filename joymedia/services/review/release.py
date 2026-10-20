"""Release checks against the footage actually used by the edit, not UI badges."""

import frappe

from joymedia.services.review.brand import BRAND_ROLES, approval_signature


def release_evidence(project_name, clips, *, lock=False):
	# At promotion, row locks serialize take/reference/review changes with the
	# decision. Queue preflight uses ordinary reads so it never holds render locks.
	if lock:
		frappe.db.sql("select name from `tabMedia Project` where name=%s for update", project_name)
	shots = frappe.db.sql(
		"select name, media_project, storyboard_beat, source_timing, storyboard_action, selected_output_asset_version, generation_prompt, image_prompt, motion_plan_json, keyframe_artifact, brand_approval_signature, brand_approved_by, brand_approved_at from `tabShot` where media_project=%s and is_removed=0 order by name"
		+ (" for update" if lock else ""),
		project_name,
		as_dict=True,
	)
	by_name = {s.name: s for s in shots}
	evidence, problems = [], []
	for clip in clips:
		if (clip.get("track_type") or "Video") != "Video" or not clip.get("enabled", 1):
			continue
		shot = by_name.get(clip.get("shot"))
		if not shot or clip.get("source_asset_version") != shot.selected_output_asset_version:
			problems.append(f"Clip {clip.get('name')} uses footage without current scene approval.")
			continue
		from joymedia.services.review.lineage import take_direction_changed

		if take_direction_changed(shot):
			problems.append(f"Scene {shot.name} still uses footage generated for an earlier direction.")
		references = frappe.db.sql(
			"select reference_role, asset_version from `tabShot Reference` where parent=%s and parenttype='Shot' order by idx"
			+ (" for update" if lock else ""),
			shot.name,
			as_dict=True,
		)
		required = any(frappe.scrub(r.reference_role or "") in BRAND_ROLES for r in references)
		if required and shot.brand_approval_signature != approval_signature(
			shot.selected_output_asset_version, references
		):
			problems.append(f"Scene {shot.name} needs product, logo and identity review for this exact take.")
		if frappe.db.exists(
			"Review Comment",
			{"shot": shot.name, "output_asset_version": clip.get("source_asset_version"), "status": "Open"},
		):
			problems.append(f"Scene {shot.name} still has unresolved review comments for this take.")
		if frappe.db.exists(
			"Video Review Feedback",
			{
				"asset_version": clip.get("source_asset_version"),
				"status": ["in", ["Open", "Investigating"]],
			},
		):
			problems.append(
				f"Scene {shot.name} still has unresolved frame or timeline feedback for this take."
			)
		evidence.append(
			{
				"shot": shot.name,
				"take": shot.selected_output_asset_version,
				"approval_signature": shot.brand_approval_signature if required else None,
				"approved_by": shot.brand_approved_by if required else None,
				"approved_at": str(shot.brand_approved_at) if required else None,
			}
		)
	if not evidence:
		problems.append("Release requires reviewed scene footage on the timeline.")
	from joymedia.services.review.release_feedback import unresolved_cut_feedback

	if unresolved_cut_feedback(project_name, clips, lock=lock):
		problems.append("Full-video feedback still needs review before release.")
	if problems:
		raise ValueError("Release blocked: " + " ".join(dict.fromkeys(problems)))
	return {"version": 1, "purpose": "release", "clips": evidence}
