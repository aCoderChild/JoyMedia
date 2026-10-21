"""Evidence-only retries over immutable held footage; inference is never replayed."""

import json
from pathlib import Path

import frappe


def _source(project_name, shot_name, attempt_name, expected_source_sha256):
	from joymedia.services.generation.takes import _ensure_scene_free, _project_shot
	from joymedia.services.project.context import _sheet_scenes
	from joymedia.services.review.admission import digest, report_for
	from joymedia.services.scene.direction import authored_action, direction_changed

	project, shot = _project_shot(project_name, shot_name)
	_ensure_scene_free(project, shot)
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	task = frappe.get_doc("Generation Task", attempt.generation_task)
	run = frappe.get_doc("Generation Run", task.generation_run)
	if (
		task.shot != shot.name
		or run.media_project != project.name
		or any(doc.status not in {"Failed", "Cancelled"} for doc in (attempt, task, run))
	):
		raise ValueError("Choose terminal held footage from this scene for evidence-only review.")
	original = report_for(attempt.name)
	if any(row.get("verdict") == "violated" for row in (original or {}).get("results", [])):
		raise ValueError("Witnessed violations require correction, not an evidence-only retry.")
	artifact = frappe.get_doc(
		"Generation Artifact", {"generation_attempt": attempt.name, "artifact_role": "Primary Video"}
	)
	path = frappe.get_doc("File", {"file_url": artifact.frappe_file}).get_full_path()
	if digest(Path(path).read_bytes()) != expected_source_sha256 or (
		original
		and (
			original.get("source_sha256") != expected_source_sha256
			or original.get("snapshot_sha256") != digest(run.project_snapshot_json.encode())
		)
	):
		raise ValueError("Held media or its original evidence changed.")
	scene = next(s for s in json.loads(run.project_snapshot_json)["shots"] if s["shot"] == shot.name)
	current = shot.as_dict()
	current["references"] = [r.as_dict() for r in shot.generation_inputs]
	current["authored_action"] = authored_action(
		shot, _sheet_scenes(project).get((shot.storyboard_beat or "", shot.source_timing or ""))
	)
	if direction_changed(current, scene):
		raise ValueError("Scene direction changed; generate footage for the revised direction.")
	return attempt, run, scene, artifact, path, original


@frappe.whitelist(methods=["POST"])
def queue_held_evidence_recheck(project_name, shot_name, attempt_name, expected_source_sha256):
	_source(project_name, shot_name, attempt_name, expected_source_sha256)
	key = frappe.generate_hash(length=16)
	frappe.enqueue(
		"joymedia.services.review.recheck.recheck_held_evidence",
		queue="long",
		timeout=1800,
		job_id=f"visual-recheck-{attempt_name}-{key}",
		enqueue_after_commit=True,
		project_name=project_name,
		shot_name=shot_name,
		attempt_name=attempt_name,
		expected_source_sha256=expected_source_sha256,
		recheck_key=key,
		user=frappe.session.user,
	)
	return {"status": "Queued", "recheck_key": key}


@frappe.whitelist()
def held_evidence_recheck_status(project_name, attempt_name, recheck_key):
	from frappe.utils.background_jobs import get_job_status

	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	task = frappe.db.get_value("Generation Attempt", attempt_name, "generation_task")
	run = frappe.db.get_value("Generation Task", task, "generation_run") if task else None
	if not run or frappe.db.get_value("Generation Run", run, "media_project") != project.name:
		raise frappe.PermissionError("This review does not belong to this project.")
	name = frappe.db.get_value(
		"Generation Artifact",
		{"generation_attempt": attempt_name, "artifact_key": f"{attempt_name}:visual_recheck:{recheck_key}"},
		"name",
	)
	if name:
		record = frappe.get_doc("Generation Artifact", name)
		path = frappe.get_doc("File", {"file_url": record.frappe_file}).get_full_path()
		report = json.loads(Path(path).read_bytes())
		return {"status": report["status"], "review_artifact": name, "findings": report.get("results", [])}
	state = get_job_status(f"visual-recheck-{attempt_name}-{recheck_key}")
	return {"status": {"queued": "Queued", "started": "Checking"}.get(state, "Failed")}


def recheck_held_evidence(project_name, shot_name, attempt_name, expected_source_sha256, recheck_key, user):
	from frappe.utils.file_manager import save_file

	from joymedia.services.review.admission import digest, freeze_policy, inspect_file

	frappe.set_user(user)
	attempt, run, scene, artifact, path, original = _source(
		project_name, shot_name, attempt_name, expected_source_sha256
	)
	policy = freeze_policy()
	frappe.db.commit()
	report = inspect_file(path, "Video", scene, policy, artifact.name)
	# Validate again after slow inspection; stale media/direction cannot be kept.
	frappe.db.commit()
	_source(project_name, shot_name, attempt_name, expected_source_sha256)
	report.update(
		stage="explicit_recheck",
		attempt=attempt.name,
		artifact=artifact.name,
		source_sha256=expected_source_sha256,
		snapshot_sha256=digest(run.project_snapshot_json.encode()),
		original_admission_sha256=digest(json.dumps(original, sort_keys=True).encode()),
		policy=policy,
		reviewed_by=user,
		original_attempt_status=attempt.status,
		original_run_status=run.status,
	)
	payload = json.dumps(report, sort_keys=True, ensure_ascii=False).encode()
	record = frappe.get_doc(
		dict(
			doctype="Generation Artifact",
			artifact_key=f"{attempt.name}:visual_recheck:{recheck_key}",
			artifact_role="Intermediate",
			generation_attempt=attempt.name,
			media_type="JSON",
			provider_locator=digest(payload),
		)
	).insert(ignore_permissions=True)
	file = save_file(
		f"{attempt.name}-visual-recheck-{recheck_key}.json",
		payload,
		"Generation Artifact",
		record.name,
		is_private=1,
	)
	record.frappe_file = file.file_url
	record.save(ignore_permissions=True)
	frappe.db.commit()
	return {"review_artifact": record.name, "status": report["status"]}


def checked_recheck(artifact_name, attempt_name, original):
	from joymedia.services.review.admission import digest, implementation_hash

	record = frappe.get_doc("Generation Artifact", artifact_name)
	if record.generation_attempt != attempt_name or not record.artifact_key.startswith(
		f"{attempt_name}:visual_recheck:"
	):
		raise ValueError("The supplementary evidence belongs to another attempt.")
	path = frappe.get_doc("File", {"file_url": record.frappe_file}).get_full_path()
	payload = Path(path).read_bytes()
	if digest(payload) != record.provider_locator:
		raise ValueError("Supplementary evidence bytes changed.")
	report = json.loads(payload)
	if (
		report.get("stage") != "explicit_recheck"
		or report.get("attempt") != attempt_name
		or report.get("original_admission_sha256") != digest(json.dumps(original, sort_keys=True).encode())
		or report.get("policy", {}).get("implementation_sha256") != implementation_hash()
		or any(row.get("verdict") == "violated" for row in (original or {}).get("results", []))
	):
		raise ValueError(
			"Supplementary evidence does not match the original failure and current review policy."
		)
	return report
