"""Keyframe-first storyboard: render and approve every scene's first frame before any video is made.

A keyframe takes about a minute, a video several. Rendering the keyframes first gives the client a real
storyboard to review, and a bad frame is replaced before video time is spent on it. An approved keyframe is
then the first frame of its scene's video run (the video pipeline's own image stage is skipped). A keyframe
approved for different inputs than the scene now has (prompt, setting, references) is stale and is ignored.
"""

import hashlib

import frappe
from frappe import _

from joymedia.services.realtime import PROJECT_UPDATED, publish_project_event

PENDING, APPROVED = "Pending Review", "Approved"


def keyframe_signature(shot):
	"""Identity of everything a keyframe is drawn from."""
	references = sorted(
		(row.reference_role or "", row.asset_version or "") for row in (shot.get("generation_inputs") or [])
	)
	text = "\x1f".join([shot.image_prompt or "", getattr(shot, "setting_prompt", None) or "", repr(references)])
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
	if shot.keyframe_signature != keyframe_signature(shot):
		return None
	if not frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file"):
		return None
	return _artifact_task(shot.keyframe_artifact)


def record_keyframe(run_name, shot_name):
	"""Store a finished keyframe task's image on its scene for review. Safe to call repeatedly."""
	from joymedia.joymedia.doctype.generation_attempt.generation_attempt import get_effective_attempt
	from joymedia.services.artifact_service import get_attempt_artifact

	for task in frappe.get_all(
		"Generation Task", filters={"generation_run": run_name, "shot": shot_name, "status": "Completed"},
		fields=["name", "workflow"], order_by="creation desc",
	):
		if frappe.db.get_value("Generation Workflow", task.workflow, "output_media_type") != "Image":
			continue
		attempt = get_effective_attempt(task.name)
		artifact = get_attempt_artifact(attempt.name, "Primary Image") if attempt else None
		if not artifact or not artifact.frappe_file:
			continue
		if frappe.db.get_value("Shot", shot_name, "keyframe_artifact") == artifact.name:
			return artifact.name
		shot = frappe.get_doc("Shot", shot_name)
		frappe.db.set_value("Shot", shot_name, {
			"keyframe_artifact": artifact.name, "keyframe_status": PENDING, "keyframe_signature": keyframe_signature(shot),
		}, update_modified=False)
		publish_project_event(frappe.db.get_value("Shot", shot_name, "media_project"), PROJECT_UPDATED, {"doctype": "Shot", "shot": shot_name})
		return artifact.name
	return None


def _project_and_shots(project_name, shot_names):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shots = []
	for name in frappe.get_all(
		"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name", order_by="shot_number asc, name asc"
	):
		if shot_names and name not in shot_names:
			continue
		shot = frappe.get_doc("Shot", name)
		if starts_scene(shot):
			shots.append(shot)
	return project, shots


@frappe.whitelist()
def generate_keyframes(project_name, shot_names=None):
	"""Render the first frame of every scene that has one (or of the named scenes), without making video."""
	from joymedia.services.scene_takes import _ensure_scene_free, _start_takes_run

	names = frappe.parse_json(shot_names) if isinstance(shot_names, str) and shot_names else (shot_names or [])
	project, shots = _project_and_shots(project_name, set(names))
	if not shots:
		frappe.throw(_("There is no scene that needs a keyframe."))
	for shot in shots:
		_ensure_scene_free(project, shot)
	return _start_takes_run(project, [shot.name for shot in shots], stage="keyframe")


@frappe.whitelist()
def set_keyframe_approval(project_name, shot_name, approved=True):
	"""Approve a scene's keyframe for video, or take the approval back."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."), frappe.PermissionError)
	approved = str(approved).lower() in {"1", "true", "yes", "on"}
	if approved:
		if not shot.keyframe_artifact:
			frappe.throw(_("Render this scene's keyframe before approving it."))
		if shot.keyframe_signature != keyframe_signature(shot):
			frappe.throw(_("This scene changed after its keyframe was drawn. Render the keyframe again."))
	frappe.db.set_value("Shot", shot.name, "keyframe_status", APPROVED if approved else PENDING, update_modified=False)
	publish_project_event(project.name, PROJECT_UPDATED, {"doctype": "Shot", "shot": shot.name})
	frappe.db.commit()
	return {"shot_name": shot.name, "keyframe_status": APPROVED if approved else PENDING}


@frappe.whitelist()
def get_project_keyframes(project_name):
	"""Each scene's keyframe for the storyboard review: image, status, and whether it is out of date."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	rows = []
	for name in frappe.get_all(
		"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name", order_by="shot_number asc, name asc"
	):
		shot = frappe.get_doc("Shot", name)
		url = (
			frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file") if shot.keyframe_artifact else None
		)
		rows.append({
			"shot": shot.name, "shot_name": shot.shot_name, "shot_number": shot.shot_number,
			"needs_keyframe": starts_scene(shot), "url": url, "status": shot.keyframe_status or "",
			"stale": bool(url) and shot.keyframe_signature != keyframe_signature(shot),
		})
	return rows
