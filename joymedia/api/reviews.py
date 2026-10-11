# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt


"""HTTP endpoints for per-shot QA reviews."""

import frappe
from frappe import _


@frappe.whitelist()
def submit_shot_review(project_name, shot_name, verdict, feedback_notes="", rejection_category="", generation_attempt=None):
	"""
	Record a QA verdict (Approved / Rejected / Needs Revision) for a shot.
	On Rejected or Needs Revision, automatically calls the AI to generate a
	suggested prompt revision from the structured feedback.
	"""
	from joymedia.services.ai_director import generate_review_revision

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()

	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	if not shot.selected_output_asset_version:
		frappe.throw(_("Generate and select a shot output before reviewing it."))

	output_asset_version = shot.selected_output_asset_version
	source_attempt = frappe.db.get_value(
		"Asset Version", output_asset_version, "source_generation_attempt"
	)
	generation_attempt = (generation_attempt or "").strip() or source_attempt
	if generation_attempt:
		attempt_task = frappe.db.get_value(
			"Generation Attempt", generation_attempt, "generation_task"
		)
		if not attempt_task or frappe.db.get_value("Generation Task", attempt_task, "shot") != shot.name:
			frappe.throw(_("Generation Attempt must belong to the reviewed Shot."))
		if source_attempt and generation_attempt != source_attempt:
			frappe.throw(_("Generation Attempt does not match the currently selected shot output."))

	verdict = (verdict or "").strip()
	if verdict not in ("Approved", "Rejected", "Needs Revision"):
		frappe.throw(_("Invalid verdict. Must be Approved, Rejected, or Needs Revision."))

	ai_suggested_revision = None
	if verdict in ("Rejected", "Needs Revision"):
		instruction_parts = []
		if rejection_category:
			instruction_parts.append(f"Issue category: {rejection_category}.")
		if (feedback_notes or "").strip():
			instruction_parts.append((feedback_notes or "").strip())
		if not instruction_parts:
			instruction_parts.append("Revise this shot to improve quality.")
		instruction = " ".join(instruction_parts)
		try:
			result = generate_review_revision(
				instruction=instruction,
				shot=shot,
				product_name=project.product_name,
				video_idea=project.video_idea,
			)
			ai_suggested_revision = result.get("generation_prompt")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Shot Review AI revision failed")

	review = frappe.new_doc("Shot Review")
	review.shot = shot_name
	review.reviewer = frappe.session.user
	review.verdict = verdict
	review.rejection_category = rejection_category or None
	review.feedback_notes = (feedback_notes or "").strip() or None
	review.ai_suggested_revision = ai_suggested_revision
	review.prompt_before_revision = shot.generation_prompt
	review.output_asset_version = output_asset_version
	if generation_attempt:
		review.generation_attempt = generation_attempt
	review.insert(ignore_permissions=True)

	frappe.db.set_value("Shot", shot_name, "review_status", verdict, update_modified=False)
	frappe.db.commit()

	return {
		"review_name": review.name,
		"shot_name": shot_name,
		"verdict": verdict,
		"ai_suggested_revision": ai_suggested_revision,
	}


def sync_shot_review_status(shot_name):
	"""Set a Shot's badge to the latest verdict for its selected immutable output.

	A Shot can switch among several takes. A verdict is meaningful only for the
	exact Asset Version the reviewer watched, never for every take of the Shot.
	"""
	shot = frappe.get_doc("Shot", shot_name)
	verdict = None
	if shot.selected_output_asset_version:
		verdict = frappe.db.get_value(
			"Shot Review",
			{"shot": shot.name, "output_asset_version": shot.selected_output_asset_version},
			"verdict",
			order_by="reviewed_at desc, creation desc",
		)
	status = verdict or "Pending Review"
	frappe.db.set_value("Shot", shot.name, "review_status", status, update_modified=False)
	return status


@frappe.whitelist()
def apply_shot_review_revision(project_name, shot_name, review_name, regenerate=False):
	"""
	Apply the AI-suggested prompt revision from a Shot Review and optionally
	trigger regeneration with retry_reason = QA Rejection.
	"""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()

	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))

	review = frappe.get_doc("Shot Review", review_name)
	if review.shot != shot_name:
		frappe.throw(_("Review does not belong to this shot."))
	if not review.ai_suggested_revision:
		frappe.throw(_("No AI-suggested revision available for this review."))
	if review.ai_revision_applied:
		frappe.throw(_("This revision has already been applied."))
	if review.output_asset_version and review.output_asset_version != shot.selected_output_asset_version:
		frappe.throw(_("Select the output reviewed by this feedback before applying its revision."))

	frappe.db.set_value("Shot", shot_name, "generation_prompt", review.ai_suggested_revision)
	frappe.db.set_value("Shot Review", review_name, "ai_revision_applied", 1, update_modified=False)

	result = {"shot_name": shot_name, "review_name": review_name, "applied": True}

	if frappe.parse_json(regenerate) if isinstance(regenerate, str) else regenerate:
		from joymedia.services.scene_takes import regenerate_scene_with_reason
		regen = regenerate_scene_with_reason(project_name, shot_name, retry_reason="QA Rejection")
		frappe.db.set_value("Shot Review", review_name, "regeneration_triggered", 1, update_modified=False)
		frappe.db.set_value("Shot", shot_name, "review_status", "Pending Review", update_modified=False)
		result["regeneration"] = regen

	frappe.db.commit()
	return result


@frappe.whitelist()
def get_shot_reviews(project_name, shot_name):
	"""Return the review history for a shot, newest first."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()

	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))

	reviews = frappe.get_all(
		"Shot Review",
		filters={"shot": shot_name},
		fields=["name", "verdict", "rejection_category", "feedback_notes", "ai_suggested_revision",
		        "ai_revision_applied", "regeneration_triggered", "reviewer", "reviewed_at", "generation_attempt",
		        "output_asset_version"],
		order_by="reviewed_at desc",
	)
	return {
		"shot_name": shot_name,
		"review_status": shot.review_status or "Pending Review",
		"reviews": reviews,
	}
