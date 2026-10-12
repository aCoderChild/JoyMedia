"""Authoritative human QA decisions for immutable generated outputs."""

import frappe
from frappe import _


HUMAN_REVIEW_KIND = "Human"
PENDING_REVIEW_STATUS = "Pending Review"


def latest_human_review_verdict(shot_name, output_asset_version):
	"""Return the latest explicit human verdict for one immutable output."""
	if not shot_name or not output_asset_version:
		return None
	return frappe.db.get_value(
		"Shot Review",
		{
			"shot": shot_name,
			"output_asset_version": output_asset_version,
			"review_kind": HUMAN_REVIEW_KIND,
		},
		"verdict",
		order_by="reviewed_at desc, creation desc",
	)


def human_review_status(shot_name, output_asset_version):
	"""Return the delivery-relevant status for one output, never an automated verdict."""
	return latest_human_review_verdict(shot_name, output_asset_version) or PENDING_REVIEW_STATUS


def is_human_approved(shot_name, output_asset_version):
	return latest_human_review_verdict(shot_name, output_asset_version) == "Approved"


def unapproved_selected_shots(project_name):
	"""Return active shots whose currently selected output lacks human approval."""
	pending = []
	for shot in frappe.get_all(
		"Shot",
		filters={"media_project": project_name, "is_removed": 0},
		fields=["name", "shot_number", "selected_output_asset_version"],
		order_by="shot_number asc",
	):
		status = human_review_status(shot.name, shot.selected_output_asset_version)
		if status != "Approved":
			pending.append(frappe._dict(shot_number=shot.shot_number, review_status=status))
	return pending


def require_approved_selected_shots(project_name):
	"""Require human approval for every active selected shot output."""
	pending = unapproved_selected_shots(project_name)
	if pending:
		details = ", ".join(f"{row.shot_number} ({row.review_status})" for row in pending)
		frappe.throw(_("QA approval is required before finishing the film. Review shots: {0}").format(details))


def require_approved_timeline_clips(project_name):
	"""Require human approval for every enabled, shot-backed video clip being exported."""
	pending = []
	for clip in frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video", "enabled": 1},
		fields=["name", "shot", "source_asset_version"],
	):
		# System-generated transitions have no source Shot and are not selectable
		# takes. Every user-visible scene clip must be approved at its exact version.
		if clip.shot and not is_human_approved(clip.shot, clip.source_asset_version):
			pending.append(clip)
	if pending:
		details = ", ".join(f"{row.shot} ({row.source_asset_version})" for row in pending)
		frappe.throw(_("QA approval is required for every video clip in the export: {0}").format(details))
