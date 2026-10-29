"""Explicit, recoverable requests from the studio tools toolbar."""

import hashlib

import frappe
from frappe import _


@frappe.whitelist(methods=["POST"])
def set_export_quality(project_name, quality):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if quality not in ("Draft 720p", "Studio 1440p60"):
		frappe.throw(_("Choose a supported export preset."))
	if project.export_status in ("Queued", "Running"):
		frappe.throw(_("Wait for the current export to finish."))
	if project.export_quality != quality:
		project.db_set("export_quality", quality, update_modified=False)
		from joymedia.services.editing.timeline import _invalidate_project_output

		_invalidate_project_output(project.name)
	return {"quality": quality}


@frappe.whitelist()
def capabilities(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	from joymedia.services.audio.plan import AUDIO_WORKFLOW_KEY
	from joymedia.services.workflows.capabilities import configured_workflow

	return {
		"effects": bool(configured_workflow("effects", legacy_key=AUDIO_WORKFLOW_KEY)),
		"face_swap": False,
	}


@frappe.whitelist(methods=["POST"])
def queue_effects(project_name, shot_name, prompt, request_id=None):
	from frappe.utils.background_jobs import get_job

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name or shot.is_removed or not shot.selected_output_asset_version:
		frappe.throw(_("Select a rendered scene before generating sound effects."))
	prompt = str(prompt or "").strip()
	if not prompt or len(prompt) > 2000:
		frappe.throw(_("Describe the sound effects using 1 to 2000 characters."))
	if not capabilities(project_name)["effects"]:
		frappe.throw(
			_("No sound-effects generation workflow is configured. You can still upload an audio file.")
		)
	if request_id is not None and len(str(request_id)) > 100:
		frappe.throw(_("Invalid sound-effects request ID."))
	fingerprint = hashlib.sha256(
		f"{shot_name}|{shot.selected_output_asset_version}|{prompt}|{request_id or ''}".encode()
	).hexdigest()[:24]
	job_id = f"joymedia-sfx-{project.name}-{fingerprint}"
	job = get_job(job_id)
	if job and job.get_status() in ("queued", "started", "deferred", "scheduled", "finished"):
		return {"job_id": job_id}
	if job:
		job.delete()
	frappe.enqueue(
		"joymedia.api.studio_tools.run_effects",
		queue="long",
		timeout=1000,
		job_id=job_id,
		deduplicate=True,
		project_name=project.name,
		shot_name=shot.name,
		source_version=shot.selected_output_asset_version,
		prompt=prompt,
		user=frappe.session.user,
		enqueue_after_commit=True,
	)
	return {"job_id": job_id}


def run_effects(project_name, shot_name, prompt, user, source_version):
	frappe.set_user(user)
	from joymedia.services.audio.plan import generate_cue_audio, place_cue_audio

	if frappe.db.get_value("Shot", shot_name, "selected_output_asset_version") != source_version:
		frappe.throw(
			_("The scene changed while sound effects were queued. Queue effects for the new version.")
		)
	result = generate_cue_audio(project_name, shot_name, role="SFX", prompt=prompt, place=False)
	# Generation can take several minutes. Never attach its result to a different take.
	if frappe.db.get_value("Shot", shot_name, "selected_output_asset_version") != source_version:
		frappe.throw(
			_("The scene changed while sound effects were generating. The audio was saved but not placed.")
		)
	place_cue_audio(project_name, shot_name, "SFX", result["asset_version"])
	return result


@frappe.whitelist()
def effects_status(project_name, job_id):
	from frappe.utils.background_jobs import get_job

	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	if not str(job_id).startswith(f"joymedia-sfx-{project.name}-"):
		frappe.throw(_("This job does not belong to this project."), frappe.PermissionError)
	job = get_job(job_id)
	if not job:
		return {"status": "missing"}
	status = getattr(job.get_status(), "value", job.get_status())
	return {
		"status": status,
		"error": (
			_("Sound-effects generation failed. Check the configured workflow and try again.")
			if status == "failed"
			else None
		),
	}
