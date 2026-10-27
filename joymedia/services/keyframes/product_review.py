"""One admission rule for authored product openings, including composed frames."""

import hashlib

import frappe


def explicit_first_frame(shot):
	frames = [
		r.asset_version
		for r in shot.generation_inputs or []
		if frappe.scrub(r.reference_role or "") == "first_frame" and r.asset_version
	]
	if len(frames) > 1:
		raise ValueError("Choose exactly one first frame for this scene.")
	return frames[0] if frames else None


def has_product(shot):
	return any(frappe.scrub(r.reference_role or "") == "product" for r in shot.generation_inputs or [])


def assert_candidate_current(project, shot, frame):
	"""Reject changed inputs or a substituted render before review or video."""
	from joymedia.services.consistency.repair import _project_asset_path

	version = frappe.get_doc("Asset Version", frame)
	proof = (frappe.parse_json(version.analysis_json or "{}") or {}).get("product_first_frame_candidate")
	if not proof:
		return False  # An arbitrary authored image needs visual review instead.
	if proof.get("shot") != shot.name or proof.get("validation_schema") != 2:
		raise ValueError("Product opening has stale placement evidence; prepare it again.")
	if not proof.get("contact", {}).get("geometry"):
		raise ValueError("Product opening needs table-relative perspective and scale evidence.")
	selected = {row.asset_version for row in project.selected_media or []}
	product = proof.get("product_asset_version")
	background = proof.get("background_asset_version")
	if not product or not background or {product, background} - selected:
		raise ValueError("Product opening sources are no longer selected for this project.")
	if not any(
		frappe.scrub(r.reference_role or "") == "product" and r.asset_version == product
		for r in shot.generation_inputs or []
	):
		raise ValueError("Product opening and scene product reference differ.")
	for asset, expected in (
		(frame, proof.get("candidate_sha256")),
		(product, proof.get("product_sha256")),
		(background, proof.get("background_sha256")),
	):
		if (
			not expected
			or hashlib.sha256(_project_asset_path(project, asset).read_bytes()).hexdigest() != expected
		):
			raise ValueError("Product opening source or candidate changed; prepare it again.")
	geometry = proof["contact"]["geometry"]
	if geometry.get("perspective_warning"):
		raise ValueError(
			"Product footprint angle conflicts with the supporting plane; choose a fitting view."
		)
	return True


def assert_product_frame_ready(project, shot):
	frame = explicit_first_frame(shot)
	if not frame or not has_product(shot):
		return
	from joymedia.services.keyframes.stage import APPROVED, keyframe_signature

	if shot.keyframe_status != APPROVED or shot.keyframe_signature != keyframe_signature(shot):
		raise ValueError(f"Scene {shot.shot_number} product opening needs review and approval before video.")
	if shot.consistency_status == "Checking" or "Critical " in str(shot.consistency_notes or ""):
		raise ValueError(f"Scene {shot.shot_number} product opening has unresolved visual findings.")
	assert_candidate_current(project, shot, frame)


def can_auto_approve_product_frame(project, shot):
	"""Only measured scale plus a clean visual audit can authorize unattended video."""
	frame = explicit_first_frame(shot)
	if not frame or not has_product(shot) or shot.consistency_status != "Passed":
		return False
	version = frappe.get_doc("Asset Version", frame)
	proof = (frappe.parse_json(version.analysis_json or "{}") or {}).get(
		"product_first_frame_candidate"
	) or {}
	if not (proof.get("contact", {}).get("geometry") or {}).get("scale_evidence"):
		return False
	try:
		assert_candidate_current(project, shot, frame)
	except ValueError:
		return False
	return True


def queue_product_frame_audit(project, shot, frame):
	"""Check every newly selected product opening, without certifying an unavailable observer."""
	from joymedia.services.runtime.endpoints import is_configured

	if not is_configured("vision"):
		shot.db_set(
			{
				"consistency_status": "Needs Review",
				"consistency_notes": "Product scale, perspective and visual fit require review; visual observer unavailable.",
			},
			update_modified=False,
		)
		return
	shot.db_set({"consistency_status": "Checking", "consistency_notes": ""}, update_modified=False)
	frappe.enqueue(
		"joymedia.services.keyframes.product_review.audit_product_frame",
		queue="joymedia_render",
		timeout=1800,
		job_id=f"joymedia-product-frame-{shot.name}-{frame}",
		deduplicate=True,
		enqueue_after_commit=True,
		project_name=project.name,
		shot_name=shot.name,
		frame=frame,
		user=frappe.session.user,
	)


def audit_product_frame(project_name, shot_name, frame, user):
	frappe.set_user(user)
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project_name or explicit_first_frame(shot) != frame:
		return
	from joymedia.services.keyframes.stage import keyframe_signature

	if shot.keyframe_signature != keyframe_signature(shot):
		shot.db_set(
			{
				"consistency_status": "Needs Review",
				"consistency_notes": "Scene inputs changed after this product frame; prepare or review a new opening.",
			},
			update_modified=False,
		)
		return
	project = frappe.get_doc("Media Project", project_name)
	try:
		assert_candidate_current(project, shot, frame)
		from joymedia.services.review.physical_audit import frame_findings

		url = frappe.db.get_value("Asset Version", frame, "file")
		findings = frame_findings(project, shot, url)
		if not findings:
			proof = (
				frappe.parse_json(frappe.db.get_value("Asset Version", frame, "analysis_json") or "{}") or {}
			).get("product_first_frame_candidate") or {}
			if not (proof.get("contact", {}).get("geometry") or {}).get("scale_evidence"):
				findings = [
					"Product-to-support size is estimated; confirm physical dimensions and visual fit before video."
				]
	except Exception as exc:
		findings = [f"Product visual review could not complete: {str(exc)[:180]}"]
	# The observer can be slow; never attach an old result to a replacement.
	shot.reload()
	if explicit_first_frame(shot) != frame:
		return
	if shot.keyframe_signature != keyframe_signature(shot):
		shot.db_set(
			{
				"consistency_status": "Needs Review",
				"consistency_notes": "Scene inputs changed after this product frame; prepare or review a new opening.",
			},
			update_modified=False,
		)
		return
	shot.db_set(
		{
			"consistency_status": "Needs Review" if findings else "Passed",
			"consistency_notes": "; ".join(findings)[:1000],
		},
		update_modified=False,
	)
	from joymedia.services.project.realtime import PROJECT_UPDATED, publish_project_event

	publish_project_event(project_name, PROJECT_UPDATED, {"doctype": "Shot", "shot": shot_name})
