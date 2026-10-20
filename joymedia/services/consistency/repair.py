"""Authorized, immutable repair of any selected take using source-art planes."""

import hashlib
import json
import tempfile
from pathlib import Path

import frappe
from frappe import _

from joymedia.services.consistency.tracking import file_hash, restore_video


def _project_asset_path(project, version):
	from joymedia.services.editing.access import _require_asset_version_access

	asset = frappe.get_doc("Asset Version", version)
	_require_asset_version_access(project, version)
	path = Path(frappe.get_doc("File", {"file_url": asset.file}).get_full_path())
	if file_hash(path) != asset.content_hash:
		raise ValueError("Source asset content no longer matches its immutable version.")
	return path


@frappe.whitelist()
def queue_source_art_repair(
	project_name, shot_name, expected_take, planes, select_result=True, source_take=None
):
	"""Queue validated controls; no untrusted filesystem paths or provider names."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	select_result = frappe.parse_json(select_result) if isinstance(select_result, str) else select_result
	if type(select_result) not in (bool, int) or select_result not in (True, False):
		frappe.throw("Choose whether to select the repaired take.")
	select_result = bool(select_result)
	import importlib.util

	if importlib.util.find_spec("cv2") is None:
		frappe.throw(_("Source-art restoration is not installed. Install JoyMedia's tracking extra."))
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."), frappe.PermissionError)
	if not expected_take or expected_take != shot.selected_output_asset_version:
		frappe.throw(_("The selected take changed. Reload the project."))
	if source_take:
		_validate_source_take(project, expected_take, source_take)
	planes = frappe.parse_json(planes) if isinstance(planes, str) else planes
	if not isinstance(planes, list) or not 1 <= len(planes) <= 8:
		frappe.throw("Supply between one and eight protected planes.")
	allowed = {
		"artwork",
		"source_quad",
		"target_quad",
		"tracking_quad",
		"occlusion",
		"visible_ranges",
		"blend_mode",
		"tracking_mode",
	}
	for plane in planes:
		if (
			not isinstance(plane, dict)
			or set(plane) - allowed
			or not {"artwork", "source_quad", "target_quad"} <= set(plane)
		):
			frappe.throw("Invalid protected-plane controls.")
		mode = plane.get("blend_mode", "source")
		if not isinstance(mode, str) or mode not in {"source", "seamless"}:
			frappe.throw("Unsupported surface blend mode.")
		tracking = plane.get("tracking_mode", "tracked")
		if (
			not isinstance(tracking, str)
			or tracking not in {"tracked", "fixed"}
			or (tracking == "fixed" and plane.get("tracking_quad") is not None)
		):
			frappe.throw("Choose tracked artwork or an explicitly fixed plane without tracking controls.")
		_project_asset_path(project, plane["artwork"])
		if plane.get("occlusion"):
			_project_asset_path(project, plane["occlusion"])
	try:
		request = json.dumps(
			[project.name, shot.name, expected_take, planes, select_result, source_take],
			sort_keys=True,
			allow_nan=False,
		)
	except ValueError, TypeError:
		frappe.throw("Protected-plane controls must contain finite JSON values.")
	identifier = "source-art-" + hashlib.sha256(request.encode()).hexdigest()[:24]
	# This is CPU work. Do not put it behind a GPU finishing job waiting for
	# inference; it can restore one scene while another scene renders.
	frappe.enqueue(
		"joymedia.services.consistency.repair.run_source_art_repair",
		queue="long",
		job_id=identifier,
		deduplicate=True,
		timeout=1800,
		enqueue_after_commit=True,
		project_name=project.name,
		shot_name=shot.name,
		expected_take=expected_take,
		planes=planes,
		select_result=select_result,
		source_take=source_take,
		user=frappe.session.user,
	)
	frappe.db.commit()
	return {"status": "Queued", "job_id": identifier}


def _validate_source_take(project, expected_take, source_take):
	"""Repair an unselected candidate without publishing it first."""
	_project_asset_path(project, source_take)
	if frappe.db.get_value("Asset Version", source_take, "media_asset") != frappe.db.get_value(
		"Asset Version", expected_take, "media_asset"
	):
		frappe.throw(_("The repair source must be a take of this scene."))


def run_source_art_repair(
	project_name, shot_name, expected_take, planes, user, select_result=True, source_take=None
):
	frappe.set_user(user)
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name or shot.selected_output_asset_version != expected_take:
		raise ValueError("Selected take changed before repair started.")
	if source_take:
		_validate_source_take(project, expected_take, source_take)
	source_take = source_take or expected_take
	from joymedia.services.editing.composer import _get_or_create_shot_output_asset, _select_output

	certificates = []
	from rq import get_current_job

	job = get_current_job()

	def cancelled():
		return job is not None and str(job.get_status(refresh=True)).lower().split(".")[-1] in {
			"canceled",
			"cancelled",
			"stopped",
		}

	with tempfile.TemporaryDirectory(prefix="joymedia-repair-") as directory:
		current = _project_asset_path(project, source_take)
		for index, plane in enumerate(planes):
			controls = dict(plane)
			artwork = _project_asset_path(project, controls.pop("artwork"))
			occlusion = controls.pop("occlusion", None)
			if occlusion:
				controls["occlusion"] = _project_asset_path(project, occlusion)
			output = Path(directory) / f"plane-{index}.mp4"
			certificates.append(restore_video(current, artwork, output, cancelled=cancelled, **controls))
			current = output
		if current.stat().st_size > 100 * 1024 * 1024:
			raise ValueError("Repair result exceeds the 100 MB storage budget; split the scene.")
		content = current.read_bytes()
	from joymedia.services.runtime.transactions import persist_result

	def promote():
		# Rendering takes time: naming counters and selections may have changed.
		# Only the short promotion retries, never the tracking or inference.
		frappe.get_doc("Media Project", project.name)._require_write_access()
		selected = frappe.db.sql(
			"select selected_output_asset_version from `tabShot` where name=%s for update", shot.name
		)[0][0]
		if selected != expected_take or cancelled():
			raise ValueError("Selected take changed during repair; result was not promoted.")
		asset = _get_or_create_shot_output_asset(shot, project.name)
		file = frappe.get_doc(
			dict(
				doctype="File",
				file_name=f"{shot.name}-source-art.mp4",
				content=content,
				is_private=1,
				attached_to_doctype="Media Asset",
				attached_to_name=asset.name,
			)
		).insert(ignore_permissions=True)
		version = frappe.get_doc(
			dict(
				doctype="Asset Version",
				media_asset=asset.name,
				file=file.file_url,
				source="Composed",
				derived_from=source_take,
				preservation_evidence_json=json.dumps(
					{"version": 1, "controls": planes, "planes": certificates}, sort_keys=True
				),
				source_generation_attempt=frappe.db.get_value(
					"Asset Version", source_take, "source_generation_attempt"
				),
			)
		).insert(ignore_permissions=True)
		if select_result:
			_select_output(shot, version.name)
			frappe.enqueue(
				"joymedia.services.editing.post_production.resume_post_production",
				queue="long",
				timeout=1800,
				enqueue_after_commit=True,
				job_id=f"source-art-finish-{version.name}",
				project_name=project.name,
			)
		return {"asset_version": version.name, "evidence": certificates, "selected": select_result}

	return persist_result(promote)


@frappe.whitelist()
def source_art_repair_status(project_name, job_id, cancel=False):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	from frappe.utils.background_jobs import get_job

	job = get_job(job_id)
	kwargs = job.kwargs.get("kwargs", {}) if job else {}
	if (
		not job
		or kwargs.get("project_name") != project.name
		or job.kwargs.get("method")
		not in {
			"joymedia.services.consistency.repair.run_source_art_repair",
			"joymedia.services.consistency.repair.repair_candidate_artwork",
		}
	):
		frappe.throw(_("Repair job does not belong to this project."), frappe.PermissionError)
	terminal = str(job.get_status(refresh=True)).lower().split(".")[-1] in {
		"finished",
		"failed",
		"canceled",
		"cancelled",
		"stopped",
	}
	if str(cancel).lower() in {"1", "true", "yes"} and not terminal:
		job.cancel()
	return {
		"status": str(job.get_status(refresh=True)),
		"result": job.return_value() if job.is_finished else None,
	}


def track_product_lock(video, lock, output, project, cancelled=None):
	"""Reuse reference-anchored tracking when a fixed source-art lock loses coverage.

	Only immutable, project-accessible patch versions qualify. No inferred plane,
	fixed-placement fallback, visibility gaps or client-authored coordinates.
	"""
	import subprocess

	from PIL import Image

	lock = frappe.parse_json(lock) if isinstance(lock, str) else lock
	canvas = lock["canvas"]
	probe = json.loads(
		subprocess.check_output(
			[
				"ffprobe",
				"-v",
				"error",
				"-select_streams",
				"v:0",
				"-show_entries",
				"stream=width,height,nb_frames,avg_frame_rate",
				"-of",
				"json",
				str(video),
			]
		)
	)["streams"][0]
	certificates = []
	screens = []
	with tempfile.TemporaryDirectory(prefix="joymedia-tracked-lock-") as directory:
		current = video
		for index, item in enumerate(lock.get("items") or []):
			if not item.get("patch_asset_version"):
				raise ValueError("Tracked fallback requires an immutable artwork patch version.")
			patch = _project_asset_path(project, item["patch_asset_version"])
			version = frappe.get_doc("Asset Version", item["patch_asset_version"])
			if version.file != item.get("file"):
				raise ValueError("Artwork patch does not match its frozen lock.")
			if item.get("coordinate_space") == "screen":
				if item.get("kind") != "typography":
					raise ValueError("Only declared typography may use screen space.")
				screens.append(item)
				continue
			with Image.open(patch) as picture:
				width, height = picture.size
			x, y, w, h = item["box"]
			sx, sy = probe["width"] / canvas[0], probe["height"] / canvas[1]
			target = [
				[x * sx, y * sy],
				[(x + w - 1) * sx, y * sy],
				[(x + w - 1) * sx, (y + h - 1) * sy],
				[x * sx, (y + h - 1) * sy],
			]
			result = Path(directory) / f"{index}.mp4"
			certificates.append(
				restore_video(
					current,
					patch,
					result,
					source_quad=[[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
					target_quad=target,
					tracking_mode="tracked",
					blend_mode="source",
					cancelled=cancelled,
				)
			)
			current = result
		if screens:
			from fractions import Fraction

			from joymedia.services.keyframes.overlay import lock_products_in_video

			result = Path(directory) / "screen-typography.mp4"
			fps = float(Fraction(probe["avg_frame_rate"]))
			lock_products_in_video(current, {"canvas": canvas, "items": screens}, result, fps)
			for item in screens:
				certificates.append(
					{
						"strategy": "screen_space_typography",
						"frames": int(probe["nb_frames"]),
						"protected_frames": int(probe["nb_frames"]),
						"patch_asset_version": item["patch_asset_version"],
					}
				)
			current = result
		if not certificates:
			raise ValueError("No immutable protected artwork was supplied.")
		Path(output).write_bytes(Path(current).read_bytes())
	return certificates


@frappe.whitelist(methods=["POST"])
def queue_candidate_artwork_repair(project_name, shot_name, attempt_name, expected_current):
	"""Reprocess saved, action-qualified inference under a new immutable repair policy."""
	from joymedia.services.review.admission import digest, freeze_policy, report_for

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name or shot.selected_output_asset_version != expected_current:
		frappe.throw(_("The selected scene changed. Reload before repairing."))
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	task = frappe.get_doc("Generation Task", attempt.generation_task)
	if task.shot != shot.name or attempt.status != "Completed" or task.status != "Completed":
		frappe.throw(_("Only completed inference from this scene can be repaired."))
	run = frappe.get_doc("Generation Run", task.generation_run)
	report = report_for(attempt.name)
	if not report or (report.get("status") != "Passed" and not report.get("review_only")):
		frappe.throw(_("Resolve action, cast and visual-check findings before artwork repair."))
	artifact = frappe.get_doc(
		"Generation Artifact", {"generation_attempt": attempt.name, "artifact_role": "Primary Video"}
	)
	content = Path(frappe.get_doc("File", {"file_url": artifact.frappe_file}).get_full_path()).read_bytes()
	if report.get("source_sha256") != digest(content) or report.get("snapshot_sha256") != digest(
		run.project_snapshot_json.encode()
	):
		frappe.throw(_("Inference evidence does not match the saved media and plan."))
	policy = freeze_policy()
	if not policy:
		frappe.throw(_("Artwork repair requires visual admission."))
	request = dict(
		project_name=project.name,
		shot_name=shot.name,
		attempt_name=attempt.name,
		expected_current=expected_current,
		policy=policy,
		source_sha256=digest(content),
		user=frappe.session.user,
	)
	identifier = "candidate-artwork-" + digest(json.dumps(request, sort_keys=True).encode())[:24]
	frappe.enqueue(
		"joymedia.services.consistency.repair.repair_candidate_artwork",
		queue="long",
		timeout=1800,
		job_id=identifier,
		deduplicate=True,
		enqueue_after_commit=True,
		**request,
	)
	frappe.db.commit()
	return dict(status="Queued", job_id=identifier)


def repair_candidate_artwork(
	project_name, shot_name, attempt_name, expected_current, policy, source_sha256, user
):
	"""Preserve the failed run, source artifact and old take; add a reviewed candidate."""
	from frappe.utils.file_manager import save_file

	from joymedia.services.editing import composer as c
	from joymedia.services.project.context import _sheet_scenes
	from joymedia.services.review.admission import digest, implementation_hash, inspect_file
	from joymedia.services.scene.direction import authored_action, direction_changed

	frappe.set_user(user)
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name or shot.selected_output_asset_version != expected_current:
		raise ValueError("Selected take changed before candidate repair.")
	if policy.get("implementation_sha256") != implementation_hash():
		raise ValueError("Repair implementation changed; queue a new repair policy.")
	attempt = frappe.get_doc("Generation Attempt", attempt_name)
	task = frappe.get_doc("Generation Task", attempt.generation_task)
	if task.shot != shot.name or attempt.status != "Completed" or task.status != "Completed":
		raise ValueError("Inference is no longer a completed candidate for this scene.")
	run = frappe.get_doc("Generation Run", task.generation_run)
	scene = next(s for s in json.loads(run.project_snapshot_json)["shots"] if s["shot"] == shot.name)
	current = shot.as_dict()
	current["references"] = [r.as_dict() for r in shot.generation_inputs]
	current["authored_action"] = authored_action(
		shot, _sheet_scenes(project).get((shot.storyboard_beat or "", shot.source_timing or ""))
	)
	if direction_changed(current, scene):
		raise ValueError("Scene direction changed since this inference.")
	asset_name = frappe.db.get_value(
		"Media Asset",
		{"media_project": project.name, "asset_name": f"{shot.name} Output", "asset_scope": "Project Output"},
		"name",
	)
	if asset_name:
		for existing in frappe.get_all(
			"Asset Version",
			filters={
				"media_asset": asset_name,
				"source_generation_attempt": attempt.name,
				"source": "Composed",
			},
			fields=["name", "edit_manifest_json"],
		):
			manifest = json.loads(existing.edit_manifest_json or "{}")
			if manifest.get("source_sha256") == source_sha256 and manifest.get("policy") == policy:
				return dict(asset_version=existing.name, selected=False, reused=True)
	artifact = frappe.get_doc(
		"Generation Artifact", {"generation_attempt": attempt.name, "artifact_role": "Primary Video"}
	)
	original = c._get_artifact_path(artifact)
	if digest(Path(original).read_bytes()) != source_sha256:
		raise ValueError("Saved native candidate changed.")
	jobs = frappe.get_all(
		"Generation Task",
		filters={"generation_run": run.name, "shot": shot.name},
		fields=[
			"name",
			"workflow",
			"segment_index",
			"segment_frame_count",
			"segment_effective_frames",
			"overlap_frames",
			"status",
		],
	)
	if len(jobs) != 1:
		raise ValueError("Repair individual completed segments before repairing a chained scene.")
	from rq import get_current_job

	job = get_current_job()

	def cancelled():
		return job is not None and str(job.get_status(refresh=True)).lower().split(".")[-1] in {
			"canceled",
			"cancelled",
			"stopped",
		}

	profile = c._get_delivery_profile(project, run.name)
	frames = c._shot_frame_count(shot, profile)
	with tempfile.TemporaryDirectory(prefix="joymedia-candidate-repair-") as directory:
		normalized = Path(directory) / "normalized.mp4"
		output = Path(directory) / "protected.mp4"
		c._normalize_segment(
			original,
			normalized,
			profile,
			int(task.segment_frame_count or 0),
			drop_first=False,
			preserve_audio=True,
		)
		lock = c.product_lock_for(run.name, shot.name, jobs)
		from joymedia.services.consistency.retention import require_coverage

		require_coverage(scene, frappe.parse_json(lock) if isinstance(lock, str) else lock)
		certificates = track_product_lock(normalized, lock, output, project, cancelled=cancelled)
		c._validate_normalized_video(output, profile, expected_frames=frames)
		finished = c._with_closing_hold(output, run.name, shot.name, profile, frames)
		c._validate_normalized_video(finished, profile, expected_frames=frames)
		checked = inspect_file(finished, "Video", scene, policy, artifact.name)
		checked.update(
			stage="tracked_artwork_repair",
			policy=policy,
			source_attempt=attempt.name,
			source_sha256=source_sha256,
			output_sha256=digest(Path(finished).read_bytes()),
		)
		proof = json.dumps(checked, sort_keys=True, ensure_ascii=False).encode()
		evidence = save_file(
			f"{attempt.name}-tracked-repair-review-{digest(proof)[:12]}.json",
			proof,
			"Generation Artifact",
			artifact.name,
			is_private=1,
		)
		if not repair_review_candidate(checked):
			frappe.db.commit()  # Retain rejection evidence even though no take is published.
			raise ValueError("Tracked repair held by visual admission. Evidence: " + evidence.file_url)
		content = Path(finished).read_bytes()
	# Long CPU/vision work never holds the selection lock.
	frappe.db.commit()
	project.reload()
	project._require_write_access()
	selected = frappe.db.sql(
		"select selected_output_asset_version from `tabShot` where name=%s for update", shot.name
	)[0][0]
	if selected != expected_current or cancelled():
		raise ValueError("Selected take changed or candidate repair was cancelled.")
	shot.reload()
	current = shot.as_dict()
	current["references"] = [r.as_dict() for r in shot.generation_inputs]
	current["authored_action"] = authored_action(
		shot, _sheet_scenes(project).get((shot.storyboard_beat or "", shot.source_timing or ""))
	)
	if direction_changed(current, scene):
		raise ValueError("Scene direction changed during candidate repair.")
	asset = c._get_or_create_shot_output_asset(shot, project.name)
	native = frappe.db.get_value(
		"Asset Version",
		{"media_asset": asset.name, "source_generation_attempt": attempt.name, "source": "Generated"},
		"name",
	)
	if not native:
		native = (
			frappe.get_doc(
				dict(
					doctype="Asset Version",
					media_asset=asset.name,
					file=artifact.frappe_file,
					source="Generated",
					source_generation_attempt=attempt.name,
				)
			)
			.insert(ignore_permissions=True)
			.name
		)
	file = save_file(f"{shot.name}-tracked-artwork.mp4", content, "Media Asset", asset.name, is_private=1)
	version = frappe.get_doc(
		dict(
			doctype="Asset Version",
			media_asset=asset.name,
			file=file.file_url,
			source="Composed",
			derived_from=native,
			source_generation_attempt=attempt.name,
			duration_seconds=shot.duration_seconds,
			fps=profile["fps"],
			preservation_evidence_json=json.dumps(
				dict(
					version=1,
					planes=certificates,
					visual_admission="Passed" if checked["status"] == "Passed" else "Review Required",
					review_file=evidence.file_url,
				)
			),
			edit_manifest_json=json.dumps(
				dict(
					method="Reference-anchored tracked artwork repair",
					original_run=run.name,
					policy=policy,
					authored_action=scene.get("authored_action"),
					source_sha256=source_sha256,
				)
			),
		)
	).insert(ignore_permissions=True)
	shot.add_comment(
		"Comment",
		f"Tracked artwork candidate {version.name} saved separately. Original inference/run and selected take preserved. Review evidence: {evidence.file_url}",
	)
	frappe.db.commit()
	return dict(asset_version=version.name, selected=False, review_file=evidence.file_url)


def repair_review_candidate(report):
	"""Retain uncertain geometry for explicit review, never automatic selection.

	Missing action/cast evidence or witnessed violations still block publication.
	The machine report remains unchanged, including every uncertainty.
	"""
	rows = report.get("results") or []
	if report.get("status") not in {"Passed", "Needs Review"} or not rows:
		return False
	if any(r.get("verdict") not in {"supported", "uncertain"} for r in rows):
		return False
	required = [r for r in rows if r.get("dimension") in {"action", "cast"}]
	return bool(
		required
		and any(r.get("id") == "authored_action" for r in required)
		and all(r.get("verdict") == "supported" for r in required)
	)
