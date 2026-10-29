"""Keyframe-first storyboard: render and approve every scene's first frame before any video is made.

A keyframe takes about a minute, a video several. Rendering the keyframes first gives the client a real
storyboard to review, and a bad frame is replaced before video time is spent on it. An approved keyframe is
then the first frame of its scene's video run (the video pipeline's own image stage is skipped). A keyframe
approved for different inputs than the scene now has (prompt, setting, references) is stale and is ignored.
"""

import hashlib

import frappe
from frappe import _

from joymedia.services.project.realtime import PROJECT_UPDATED, publish_project_event

PENDING, APPROVED = "Pending Review", "Approved"


def keyframe_signature(shot):
	"""Identity of everything a keyframe is drawn from."""
	references = sorted(
		(row.reference_role or "", row.asset_version or "") for row in (shot.get("generation_inputs") or [])
	)
	mode = getattr(shot, "character_mode", None) or (
		frappe.db.get_value("Media Project", shot.media_project, "character_mode")
		if shot.get("media_project")
		else ""
	)
	parts = [
		shot.image_prompt or "",
		getattr(shot, "setting_prompt", None) or "",
		mode or "",
		repr(references),
	]
	if shot.get("media_project"):
		from joymedia.services.intake.references import preservation_modes

		parts.append(frappe.as_json(preservation_modes(frappe.get_doc("Media Project", shot.media_project))))
	from joymedia.services.scene.contract import opening_instruction

	staging = opening_instruction(shot.get("motion_plan_json"), shot.get("duration_seconds"))
	if staging:
		parts.append(staging)
	from joymedia.services.scene.artwork import placements

	artwork = placements(shot.get("motion_plan_json"))
	if artwork:
		parts.append(frappe.as_json(artwork))
	if shot.get("views_json"):
		parts.append(shot.views_json)  # only a split screen's: other scenes' frames keep their signature
	from joymedia.services.consistency.retention import policy

	retention = policy()
	if retention:
		parts.append(
			frappe.as_json(
				{
					k: v
					for k, v in retention.items()
					if k not in {"source_hold_pipeline", "source_hold_workflow"}
				}
			)
		)
	text = "\x1f".join(parts)
	return hashlib.sha256(text.encode()).hexdigest()[:20]


def starts_scene(shot):
	"""Whether the scene has its own opening frame (continuing scenes start from the previous video's last frame)."""
	return int(shot.shot_number or 0) <= 1 or shot.continuity_mode != "Continue"


def _artifact_task(artifact_name):
	attempt = frappe.db.get_value("Generation Artifact", artifact_name, "generation_attempt")
	return frappe.db.get_value("Generation Attempt", attempt, "generation_task") if attempt else None


def approved_keyframe_task(shot):
	"""The Generation Task whose Primary Image is this scene's approved, current keyframe, else None."""
	if shot.get("keyframe_status") != APPROVED or not shot.get("keyframe_artifact"):
		return None
	if "Critical " in str(shot.get("consistency_notes") or ""):
		return None
	if shot.keyframe_signature != keyframe_signature(shot):
		return None
	if not frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file"):
		return None
	return _artifact_task(shot.keyframe_artifact)


def record_keyframe(run_name, shot_name):
	"""Store a finished keyframe task's image on its scene for review. Safe to call repeatedly."""
	from joymedia.joymedia.doctype.generation_attempt.generation_attempt import get_effective_attempt
	from joymedia.services.generation.artifacts import get_attempt_artifact

	for task in frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name, "shot": shot_name, "status": "Completed"},
		fields=["name", "workflow"],
		order_by="creation desc",
	):
		if frappe.db.get_value("Generation Workflow", task.workflow, "output_media_type") != "Image":
			continue
		attempt = get_effective_attempt(task.name)
		artifact = get_attempt_artifact(attempt.name, "Primary Image") if attempt else None
		if not artifact or not artifact.frappe_file:
			continue
		attach_keyframe_to_project(
			artifact.frappe_file, frappe.db.get_value("Shot", shot_name, "media_project")
		)
		if frappe.db.get_value("Shot", shot_name, "keyframe_artifact") == artifact.name:
			return artifact.name
		shot = frappe.get_doc("Shot", shot_name)
		frappe.db.set_value(
			"Shot",
			shot_name,
			{
				"keyframe_artifact": artifact.name,
				"keyframe_status": PENDING,
				"keyframe_signature": keyframe_signature(shot),
			},
			update_modified=False,
		)
		from joymedia.services.review.consistency import queue_check

		queue_check(shot_name, "frame")
		publish_project_event(
			frappe.db.get_value("Shot", shot_name, "media_project"),
			PROJECT_UPDATED,
			{"doctype": "Shot", "shot": shot_name},
		)
		return artifact.name
	return None


def attach_keyframe_to_project(file_url, project_name):
	"""Let the project's owner open a keyframe picture.

	A rendered picture is attached to its Generation Artifact, which only a System Manager may read, so the browser got
	403 for everyone else. A private file is readable by whoever may read the document it is attached to; attached to the
	Media Project, that is exactly the project's owner (and the staff roles).
	"""
	frappe.db.set_value(
		"File",
		{"file_url": file_url, "attached_to_doctype": ["!=", "Media Project"]},
		{"attached_to_doctype": "Media Project", "attached_to_name": project_name},
		update_modified=False,
	)


def _project_and_shots(project_name, shot_names):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shots = []
	for name in frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		pluck="name",
		order_by="shot_number asc, name asc",
	):
		if shot_names and name not in shot_names:
			continue
		shot = frappe.get_doc("Shot", name)
		if starts_scene(shot):
			shots.append(shot)
	return project, shots


@frappe.whitelist()
def generate_keyframes(project_name, shot_names=None, draw_places=True, automatic=False, seed=None):
	"""Render the first frame of every scene that has one (or of the named scenes), without making video.

	A place none of the scenes has a picture of yet is drawn first, in the background, so that all scenes set there
	are drawn in the same room (services/keyframes/locations.py); the frames follow when it is ready."""
	from joymedia.services.generation.takes import _ensure_scene_free, _start_takes_run
	from joymedia.services.keyframes.locations import assign_places, missing_places, missing_views
	from joymedia.services.review.consistency import reset_redos

	if isinstance(seed, str) and seed.isdecimal():
		seed = int(seed)
	if seed is not None and (type(seed) is not int or not 0 <= seed < 2_147_483_648):
		frappe.throw(_("Image seed must be an integer between 0 and 2147483647."))
	names = (
		frappe.parse_json(shot_names) if isinstance(shot_names, str) and shot_names else (shot_names or [])
	)
	# Frappe form values arrive as strings over the HTTP API.  ``bool("false")``
	# is true, which previously made a caller explicitly requesting no location
	# render submit an unexpected extra ComfyUI job.
	if isinstance(draw_places, str):
		draw_places = draw_places.strip().lower() not in {"", "0", "false", "no", "off"}
	else:
		draw_places = bool(draw_places)
	project, shots = _project_and_shots(project_name, set(names))
	if not shots:
		frappe.throw(_("There is no scene that needs a keyframe."))
	for shot in shots:
		_ensure_scene_free(project, shot)
		if not automatic:
			# A person asked for this drawing: the automatic check may redo it again (services/review/consistency.py).
			reset_redos(shot.name)
	if draw_places and (missing_places(project, shots) or missing_views(project, shots)):
		if seed is not None:
			frappe.throw(_("Draw the place reference before replaying a first-frame seed."))
		if project.storyboard_approval_status != "Approved":
			frappe.throw(
				_("Approve the storyboard first: the first frames are drawn from the approved scenes.")
			)
		frappe.enqueue(
			"joymedia.services.keyframes.locations.draw_places_then_frames",
			queue="long",
			timeout=3600,
			job_id=f"joymedia-places-{project.name}",
			deduplicate=True,
			project_name=project.name,
			shot_names=[shot.name for shot in shots],
			user=frappe.session.user,
		)
		return {"status": "Drawing places"}
	if assign_places(project, shots):
		project.reload()  # the approval was sealed again with the places in it
	return _start_takes_run(
		project,
		[shot.name for shot in shots],
		stage="keyframe",
		**({"keyframe_seed": seed} if seed is not None else {}),
	)


@frappe.whitelist()
def set_keyframe_approval(project_name, shot_name, approved=True):
	"""Approve a scene's keyframe for video, or take the approval back."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."), frappe.PermissionError)
	approved = str(approved).lower() in {"1", "true", "yes", "on"}
	from joymedia.services.keyframes.product_review import (
		assert_candidate_current,
		explicit_first_frame,
		has_product,
	)

	explicit_product = explicit_first_frame(shot) if has_product(shot) else None
	if approved:
		if shot.consistency_status in {"Checking", "Redrawing"}:
			frappe.throw(_("Wait for this frame's visual checks and corrections to finish."))
		if "Critical " in str(shot.consistency_notes or ""):
			frappe.throw(_("Resolve this frame's critical physical or consistency findings before approval."))
		if not shot.keyframe_artifact and not explicit_product:
			frappe.throw(_("Render this scene's keyframe before approving it."))
		if shot.keyframe_signature != keyframe_signature(shot):
			frappe.throw(_("This scene changed after its keyframe was drawn. Render the keyframe again."))
		if explicit_product:
			assert_candidate_current(project, shot, explicit_product)
			if shot.consistency_status == "Checking":
				frappe.throw(_("Wait for the product opening review to finish."))
			if "Critical " in str(shot.consistency_notes or ""):
				frappe.throw(_("Resolve the product opening's critical visual findings before approval."))
	frappe.db.set_value(
		"Shot", shot.name, "keyframe_status", APPROVED if approved else PENDING, update_modified=False
	)
	if approved:
		# The frame is settled; the take made from it gets its own automatic redos.
		frappe.db.set_value("Shot", shot.name, "consistency_retries", 0, update_modified=False)
		if shot.get("consistency_status") in {"Redrawing", "Checking"}:
			# A queued machine concern must not redraw an explicitly accepted frame
			# when another run ends. Keep its notes visible for the reviewer.
			frappe.db.set_value(
				"Shot",
				shot.name,
				"consistency_status",
				"Needs Review" if shot.get("consistency_notes") else "Not Checked",
				update_modified=False,
			)
	publish_project_event(project.name, PROJECT_UPDATED, {"doctype": "Shot", "shot": shot.name})
	frappe.db.commit()
	return {"shot_name": shot.name, "keyframe_status": APPROVED if approved else PENDING}


@frappe.whitelist()
def get_project_keyframes(project_name):
	"""Each scene's keyframe for the storyboard review: image, status, and whether it is out of date."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	from joymedia.services.keyframes.product_review import has_product
	from joymedia.services.workflows.capabilities import controls

	reference_only = bool(
		project.workflow
		and "reference_only" in controls(frappe.get_doc("Generation Workflow", project.workflow))
	)
	rows = []
	for name in frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		pluck="name",
		order_by="shot_number asc, name asc",
	):
		shot = frappe.get_doc("Shot", name)
		if reference_only:
			rows.append(
				{
					"shot": shot.name,
					"shot_name": shot.shot_name,
					"shot_number": shot.shot_number,
					"needs_keyframe": False,
					"url": None,
					"status": "Reference conditioned",
					"stale": False,
				}
			)
			continue
		explicit = [
			r.asset_version
			for r in shot.generation_inputs or []
			if frappe.scrub(r.reference_role or "") == "first_frame" and r.asset_version
		]
		if len(explicit) > 1:
			frappe.throw(_("Choose exactly one authored first frame."))
		explicit_product = bool(explicit and has_product(shot))
		url = (
			frappe.db.get_value("Asset Version", explicit[0], "file")
			if len(explicit) == 1
			else frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
			if shot.keyframe_artifact
			else None
		)
		if url:
			from joymedia.services.project.context import _get_asset_file_url

			media_asset = frappe.db.get_value("Asset Version", explicit[0], "media_asset") if explicit else None
			url = _get_asset_file_url(media_asset, url)
		rows.append(
			{
				"shot": shot.name,
				"shot_name": shot.shot_name,
				"shot_number": shot.shot_number,
				"needs_keyframe": starts_scene(shot) and (not explicit or explicit_product),
				"authored_frame": bool(explicit),
				"url": url,
				"status": (shot.keyframe_status or PENDING)
				if explicit_product
				else (APPROVED if explicit else shot.keyframe_status or ""),
				"stale": bool(url)
				and (explicit_product or not explicit)
				and shot.keyframe_signature != keyframe_signature(shot),
				"review_status": shot.consistency_status or "",
				"review_notes": shot.consistency_notes or "",
			}
		)
	return rows
