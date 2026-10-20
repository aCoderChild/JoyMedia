"""Human brand review, bound to the selected take and immutable reference versions.

The action/count vision judge cannot certify fine mascot identity or typography.
Review exports stay available; their brand approval is reported separately.
"""

import hashlib
import json

import frappe
from frappe import _

from joymedia.services.project.realtime import PROJECT_UPDATED, publish_project_event

BRAND_ROLES = {"character", "product", "logo", "person"}


def approval_signature(take, references):
	assets = sorted(
		{
			(frappe.scrub(r.get("reference_role") or r.get("input_role") or ""), r.get("asset_version"))
			for r in references or []
			if r.get("asset_version")
		}
	)
	return hashlib.sha256(json.dumps([take, assets], ensure_ascii=False).encode()).hexdigest()


def review_state(shot, references):
	required = any(frappe.scrub(r.get("reference_role") or "") in BRAND_ROLES for r in references or [])
	take = shot.get("selected_output_asset_version")
	approved = bool(
		required and take and shot.get("brand_approval_signature") == approval_signature(take, references)
	)
	return {
		"required": required,
		"status": "Approved"
		if approved
		else "Needs Review"
		if take and required
		else "Awaiting Take"
		if required
		else "Not Required",
		"approved_by": shot.get("brand_approved_by") if approved else None,
		"approved_at": shot.get("brand_approved_at") if approved else None,
	}


@frappe.whitelist()
def approve_scene_brand(project_name, shot_name, expected_take, approved=True):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	# Serialize approval against take selection: an old browser cannot approve a newer take.
	frappe.db.sql("select name from `tabShot` where name=%s for update", shot_name)
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."), frappe.PermissionError)
	if not expected_take or expected_take != shot.selected_output_asset_version:
		frappe.throw(_("The selected take changed. Review the current video before approving its branding."))
	references = [
		dict(reference_role=r.reference_role, asset_version=r.asset_version) for r in shot.generation_inputs
	]
	approve = str(approved).lower() in {"1", "true", "yes", "on"}
	frappe.db.set_value(
		"Shot",
		shot.name,
		{
			"brand_approval_signature": approval_signature(expected_take, references) if approve else "",
			"brand_approved_by": frappe.session.user if approve else None,
			"brand_approved_at": frappe.utils.now_datetime() if approve else None,
		},
		update_modified=False,
	)
	publish_project_event(project.name, PROJECT_UPDATED, {"doctype": "Shot", "shot": shot.name})
	frappe.db.commit()
	return {"status": "Approved" if approve else "Needs Review", "take": expected_take}
