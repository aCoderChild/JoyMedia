"""Pre-animation/pre-selection admission, using the existing evidence evaluator.

Policy, direction and judge are frozen with the run. Failed/unknown evidence never
unlocks a dependency. A quality reroll changes the seed, not the authored action.
VBench-style dimensions and VideoPhy-style rule evidence remain separate from
source-art coverage and human brand approval; a sampled pass certifies neither.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import frappe

from joymedia.services.runtime.endpoints import endpoint
from joymedia.services.scene.contract import opening_claims, read_contract
from joymedia.services.scene.evidence import SequenceCheck, claims_for, digest, sample_times

VERSION = 1
REJECTED = "Visual admission rejected"


def implementation_hash():
	root = Path(__file__).resolve().parents[1]
	return digest(
		b"".join(
			(root / name).read_bytes()
			for name in (
				"review/admission.py",
				"review/consistency.py",
				"runtime/sampling.py",
				"../workflow_adapters/graphs/prompt_sampling.json",
				"scene/evidence.py",
				"scene/contract.py",
				"consistency/retention.py",
				"generation/preparation.py",
				"generation/ingestor.py",
				"generation/orchestrator.py",
				"generation/takes.py",
				"generation/run_state.py",
				"editing/composer.py",
				"consistency/repair.py",
				"consistency/tracking.py",
				"consistency/surfaces.py",
				"keyframes/overlay.py",
				"workflows/resolver.py",
				"project/versions.py",
				"scene/direction.py",
				"planning/signature.py",
			)
		)
	)


def freeze_policy():
	value = frappe.conf.get("joymedia_generation_quality") or {}
	if not isinstance(value, dict) or type(value.get("enabled", False)) is not bool:
		raise ValueError("Visual admission configuration requires a boolean enabled flag.")
	if not value.get("enabled"):
		return None
	configured = endpoint("vision")
	judge = {
		key: configured[key]
		for key in ("base_url", "model", "timeout", "structured_output", "revision")
		if key in configured
	}
	return {
		"version": VERSION,
		"judge": judge,
		"implementation_sha256": implementation_hash(),
		"max_quality_retries": 1,
		"limitations": "Sampled visual screening; source coverage and brand approval remain independent.",
	}


def context_for(attempt):
	job = frappe.get_doc("Generation Task", attempt.generation_task)
	run = frappe.get_doc("Generation Run", job.generation_run)
	snapshot = frappe.parse_json(run.project_snapshot_json or "{}") or {}
	policy = snapshot.get("visual_admission")
	scene = next((s for s in snapshot.get("shots", []) if s.get("shot") == job.shot), None)
	if policy and (policy.get("version") != VERSION or not scene):
		raise ValueError("Unsupported or incomplete frozen visual admission policy.")
	if policy and policy.get("implementation_sha256") != implementation_hash():
		raise ValueError(
			"The visual admission implementation changed. Regenerate from the current plan rather than reinterpreting this frozen run."
		)
	return job, run, scene, policy


def screening_claims(scene, video):
	"""No product, species, furniture topology or model names in these defaults."""
	plan, duration = scene.get("motion_plan_json"), scene.get("duration_seconds")
	if video:
		claims = claims_for(plan, duration, scene.get("generation_prompt"))
		if scene.get("authored_action"):
			claims.append(
				{
					"id": "authored_action",
					"dimension": "action",
					"mode": "occurrence",
					"claim": scene["authored_action"],
				}
			)
	else:
		claims = [
			{
				"id": "opening",
				"dimension": "staging",
				"claim": "The visible starting pose and objects agree with this direction. Future actions need not have occurred: "
				+ str(scene.get("image_prompt") or scene.get("generation_prompt") or "")[:1800],
			},
			{
				"id": "staging",
				"dimension": "physics",
				"claim": "Visible parts belong to their objects; actors and objects have plausible support, reachable contact and connected anatomy. Do not infer hidden support or anatomy.",
			},
		]
		claims += [
			{"id": f"opening.{i}", "dimension": "staging", "claim": c}
			for i, c in enumerate(opening_claims(plan, duration))
		]
	roles = {
		str(r.get("reference_role") or r.get("input_role") or "").lower() for r in scene.get("references", [])
	}
	if not roles.intersection({"person", "people", "talent"}):
		claims.append(
			{
				"id": "unrequested_human",
				"dimension": "cast",
				"mode": "invariant",
				"claim": "No real human, human hand, human fingers, arm or other human body part is physically present. "
				"The approved scene has no Person reference. Stylized reference-character paws and printed artwork are not human limbs.",
			}
		)
	return claims


def requires_geometry_review(scene):
	if scene.get("render_strategy") == "controlled_source_presentation":
		return False
	contract = read_contract(scene.get("motion_plan_json"), scene.get("duration_seconds")) or {}
	actors = any(
		str(r.get("reference_role") or r.get("input_role") or "").lower()
		in {"character", "person", "people", "talent"}
		for r in scene.get("references", [])
	)
	return actors or any(contract.get(k) for k in ("relations", "parts", "proportions"))


def needs_frame_approval(snapshot, scene, keyframe_stage=False, *, reference_only=False):
	# Direct reference generation has no opening-frame control to approve.
	# Its decoded video still passes the same physical/action/cast admission.
	if reference_only:
		return False
	if not snapshot.get("visual_admission") or keyframe_stage or not requires_geometry_review(scene):
		return False
	if scene.get("keyframe_task") or any(
		str(r.get("reference_role") or "").lower() == "first_frame" and r.get("asset_version")
		for r in scene.get("references", [])
	):
		return False
	# Continuations consume the predecessor's admitted decoded last frame. They
	# cannot have an independent first frame; require a qualified upstream anchor.
	if str(scene.get("continuity_mode") or "").casefold() == "continue":
		scenes = snapshot.get("shots") or []
		index = next(
			(
				i
				for i, item in enumerate(scenes)
				if item is scene or (item.get("shot") == scene.get("shot") and scene.get("shot"))
			),
			-1,
		)
		if index > 0:
			return needs_frame_approval(snapshot, scenes[index - 1])
	return True


def inspect_file(path, media_type, scene, policy, evidence_name):
	from joymedia.services.review.consistency import run_temporal_check

	video = media_type == "Video"
	data = Path(path).read_bytes()
	claims = screening_claims(scene, video)
	if video:
		probe = json.loads(
			subprocess.check_output(
				["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)], timeout=30
			)
		)
		stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
		from fractions import Fraction

		fps = float(Fraction(stream["avg_frame_rate"]))
		count = int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else None
		times = sample_times(float(stream["duration"]), fps, scene.get("motion_plan_json"), frame_count=count)
		pictures = []
		with tempfile.TemporaryDirectory(prefix="joymedia-screen-") as folder:
			for i, t in enumerate(times):
				target = Path(folder) / f"{i}.png"
				subprocess.run(
					[
						"ffmpeg",
						"-v",
						"error",
						"-y",
						"-ss",
						str(t),
						"-i",
						str(path),
						"-frames:v",
						"1",
						str(target),
					],
					check=True,
					capture_output=True,
					timeout=30,
				)
				pictures.append(target.read_bytes())
	else:
		pictures, times = [data], [0]
	metadata = [
		dict(index=i, time=t, frame_index=round(t * fps) if video else 0, sha256=digest(pictures[i]))
		for i, t in enumerate(times)
	]
	# Negative logical claims are unreliable with some vision runtimes (the
	# same answer can describe a hand and endorse "no hand"). Observe presence
	# positively, then negate a strict boolean in code, not in the model.
	no_human = any(c["id"] == "unrequested_human" for c in claims)
	claims = [c for c in claims if c["id"] != "unrequested_human"]
	check = SequenceCheck(
		pictures,
		metadata,
		claims,
		dict(
			source_sha256=digest(data),
			direction_sha256=digest(json.dumps(scene, sort_keys=True).encode()),
			required_claim_ids=[c["id"] for c in claims],
			evidence_doctype="Generation Artifact",
			evidence_name=evidence_name,
		),
	)
	report = run_temporal_check(check, configured=frappe._dict(policy["judge"]))
	from joymedia.services.review.consistency import COUNT, ask

	identities = (scene.get("consistency_plan") or {}).get("identities")
	cast = [
		r
		for r in (identities if identities is not None else scene.get("references", []))
		if str(r.get("role") or r.get("reference_role") or "").lower()
		in {"character", "person", "people", "talent"}
	]
	counts = []
	for i, picture in enumerate(pictures):
		answer = ask(picture, COUNT, configured=frappe._dict(policy["judge"]))
		value, reason = answer.get("count"), answer.get("reason")
		valid = type(value) is int and value >= 0 and isinstance(reason, str) and bool(reason.strip())
		counts.append(dict(frame=i, count=value if valid else None, reason=str(reason or "")[:500]))
	excess = [r for r in counts if r["count"] is not None and r["count"] > len(cast)]
	unknown = [r for r in counts if r["count"] is None]
	report["results"].append(
		dict(
			id="cast_inventory",
			dimension="cast",
			claim=f"At most {len(cast)} physical foreground reference actors; printed characters do not count.",
			verdict="violated" if excess else "uncertain" if unknown else "supported",
			frames=[r["frame"] for r in (excess or unknown or counts)],
			reason="; ".join(dict.fromkeys(r["reason"] for r in (excess or unknown or counts)))[:1000],
		)
	)
	report["cast_observations"] = counts
	report["required_claim_ids"].append("cast_inventory")
	# Broad identity/topology screening compares pixels with approved references,
	# not with a text description invented by the same generator. It cannot
	# certify typography or fine identity, which retain their independent gates.
	sources = [
		r
		for r in (scene.get("references") or [])
		if str(r.get("reference_role") or "").lower() in {"character", "person"} and r.get("asset_version")
	]
	if len(sources) > 4:
		raise ValueError("Split scenes with more than four identity-reference views for visual screening.")
	witnesses = _identity_witnesses(counts)
	for source in sources:
		asset = frappe.get_doc("Asset Version", source["asset_version"])
		source_path = frappe.get_doc("File", {"file_url": asset.file}).get_full_path()
		reference = Path(source_path).read_bytes()
		if digest(reference) != asset.content_hash:
			raise ValueError("Approved identity reference bytes changed.")
		observations = []
		for i in witnesses:
			answer = ask(
				[reference, pictures[i]],
				"Image 1 is the approved reference; image 2 is the candidate scene. Compare only features visible in BOTH views. "
				"Cropping, perspective and image scale do not establish different physical size, age or body proportions. "
				"A close view of a body part is not a smaller whole subject. Do not invent the hidden face or body. "
				"Does the candidate keep the reference subject's visible distinctive shape, morphology and body-part proportions, "
				"without invented human anatomy, extra parts or elongated limbs? Pose, camera and plausible occlusion may differ. "
				"Do not judge text or logos. Answer null when identity or topology cannot be compared. "
				"Return only JSON with answer true, false or null and reason describing visible evidence.",
				configured=frappe._dict(policy["judge"]),
			)
			value, reason = answer.get("answer"), answer.get("reason")
			valid = type(value) is bool and isinstance(reason, str) and bool(reason.strip())
			observations.append(
				dict(frame=i, answer=value if valid else None, reason=str(reason or "")[:500])
			)
		if observations:
			failures = [r for r in observations if r["answer"] is False]
			unknowns = [r for r in observations if r["answer"] is None]
			identifier = "reference." + asset.name
			report["results"].append(
				dict(
					id=identifier,
					dimension="identity",
					claim="Visible identity and topology agree with approved reference " + asset.name,
					verdict="violated" if failures else "uncertain" if unknowns else "supported",
					frames=[r["frame"] for r in (failures or unknowns or observations)],
					reason="; ".join(r["reason"] for r in (failures or unknowns or observations))[:1000],
					reference_sha256=digest(reference),
					observations=observations,
				)
			)
			report["required_claim_ids"].append(identifier)
	if no_human:
		from joymedia.services.review.consistency import OUTSIDER, ask

		observations = []
		for i, picture in enumerate(pictures):
			answer = ask(picture, OUTSIDER, configured=frappe._dict(policy["judge"]))
			value, reason = answer.get("answer"), answer.get("reason")
			valid = type(value) is bool and isinstance(reason, str) and bool(reason.strip())
			observations.append(
				dict(
					frame=i,
					present=value if valid else None,
					reason=reason[:500] if valid else "Missing or malformed presence evidence.",
				)
			)
		present = [r for r in observations if r["present"] is True]
		uncertain = [r for r in observations if r["present"] is None]
		report["results"].append(
			dict(
				id="unrequested_human",
				dimension="cast",
				claim="No unrequested human body part is physically present.",
				verdict="violated" if present else "uncertain" if uncertain else "supported",
				frames=[r["frame"] for r in (present or uncertain or observations)],
				reason="; ".join(dict.fromkeys(r["reason"] for r in (present or uncertain or observations)))[
					:1000
				],
			)
		)
		report["presence_observations"] = observations
		report["required_claim_ids"].append("unrequested_human")
	if requires_geometry_review(scene):
		# Live counterexamples demonstrate that this judge can endorse both
		# unsupported product placement and invented limb proportions. A model
		# agreeing with its own prose is not independent geometric evidence.
		# Hold the frame before animation, rather than claiming calibrated
		# physical acceptance or spending rerolls on uncertainty alone.
		report["results"].append(
			dict(
				id="geometry_qualification",
				dimension="qualification",
				claim="Interacting or deforming geometry has independently qualified support and topology.",
				verdict="uncertain",
				frames=[0],
				reason="Sampled language-model judgments do not establish measured support or reference topology. Use qualified geometry/motion controls or administrator review; do not automatically animate this unqualified frame.",
			)
		)
		report["required_claim_ids"].append("geometry_qualification")
	report["status"] = (
		"Passed" if all(r["verdict"] == "supported" for r in report["results"]) else "Needs Review"
	)
	# Physics uncertainty retains a manual-review candidate, never an automatic
	# approval. Composition returns False for review-only evidence; witnessed
	# violations and uncertain action/cast claims still stop the task.
	report["review_only"] = bool(
		report["status"] == "Needs Review"
		and all(
			r["verdict"] == "supported"
			or (
				(r.get("dimension") == "physics" or r["id"] in {"geometry_qualification", "physics"})
				and r["verdict"] == "uncertain"
			)
			for r in report["results"]
		)
	)
	report["sequence_evidence_file"] = report.pop("evidence_file", None)
	return report


def _identity_witnesses(counts):
	"""Prefer co-visible actor views over entry/exit slivers; count every frame separately."""
	visible = [row["frame"] for row in counts if row["count"] is not None and row["count"] > 0]
	if len(visible) <= 4:
		return visible
	if len(visible) == len(counts):
		return [visible[0], visible[len(visible) // 2], visible[-1]]
	# A newly entering or departing actor is often only a few fingers at the
	# visibility boundary. Keep three temporally separated comparisons in the
	# interior; never turn an unknown identity response into a positive one.
	return [visible[len(visible) // 4], visible[len(visible) // 2], visible[3 * len(visible) // 4]]


def report_for(attempt_name):
	name = frappe.db.get_value(
		"Generation Artifact", {"artifact_key": f"{attempt_name}:visual_admission:v{VERSION}"}, "name"
	)
	if not name:
		return None
	artifact = frappe.get_doc("Generation Artifact", name)
	path = frappe.get_doc("File", {"file_url": artifact.frappe_file}).get_full_path()
	payload = Path(path).read_bytes()
	if artifact.provider_locator != digest(payload):
		raise ValueError("Visual admission report bytes changed.")
	return json.loads(payload)


def store_report(attempt, artifact, report):
	from frappe.utils.file_manager import save_file

	key = f"{attempt.name}:visual_admission:v{VERSION}"
	existing = frappe.db.get_value("Generation Artifact", {"artifact_key": key}, "name")
	if existing:
		return existing
	payload = json.dumps(report, sort_keys=True, ensure_ascii=False).encode()
	record = frappe.get_doc(
		dict(
			doctype="Generation Artifact",
			artifact_key=key,
			artifact_role="Intermediate",
			generation_attempt=attempt.name,
			media_type="JSON",
			provider_locator=digest(payload),
		)
	).insert(ignore_permissions=True)
	file = save_file(
		f"{attempt.name}-visual-admission.json", payload, "Generation Artifact", record.name, is_private=1
	)
	record.frappe_file = file.file_url
	record.save(ignore_permissions=True)
	return record.name


def gate_attempt(attempt, artifact, history, last_frame):
	"""None means historical/unconfigured. Pending keeps the task unavailable."""
	if artifact.media_type not in {"Image", "Video"}:
		return None
	_job, run, _scene, policy = context_for(attempt)
	if not policy:
		return None
	report = report_for(attempt.name)
	if report:
		path = frappe.get_doc("File", {"file_url": artifact.frappe_file}).get_full_path()
		if report.get("source_sha256") != digest(Path(path).read_bytes()) or report.get(
			"snapshot_sha256"
		) != digest(run.project_snapshot_json.encode()):
			raise ValueError("Visual admission evidence does not match the immutable media and plan.")
		return report
	# Provider completion is not task completion. Commit admission before I/O;
	# the worker then rechecks cancellation and the exact attempt before writing.
	if attempt.status != "Running":
		attempt.status = "Running"
		attempt.save(ignore_permissions=True)
	frappe.enqueue(
		"joymedia.services.review.admission.run_gate",
		queue="long",
		timeout=600,
		job_id=f"visual-admission-{attempt.name}",
		deduplicate=True,
		enqueue_after_commit=True,
		attempt_name=attempt.name,
		artifact_name=artifact.name,
		history=history,
		last_frame_name=last_frame.name if last_frame else None,
		user=frappe.session.user,
	)
	return {"status": "Checking"}


def run_gate(attempt_name, artifact_name, history, last_frame_name, user):
	from frappe.utils.synchronization import filelock

	from joymedia.services.generation.ingestor import _complete_attempt

	frappe.set_user(user)
	with filelock(f"visual-admission-{attempt_name}"):
		attempt = frappe.get_doc("Generation Attempt", attempt_name)
		job, run, scene, policy = context_for(attempt)
		if (
			attempt.status not in {"Running", "Queued"}
			or job.status in {"Cancelled", "Failed"}
			or run.status in {"Cancelled", "Failed"}
		):
			return
		artifact = frappe.get_doc("Generation Artifact", artifact_name)
		if artifact.generation_attempt != attempt.name:
			raise ValueError("Visual admission artifact belongs to another attempt.")
		path = frappe.get_doc("File", {"file_url": artifact.frappe_file}).get_full_path()
		snapshot_hash, content_hash = (
			digest(run.project_snapshot_json.encode()),
			digest(Path(path).read_bytes()),
		)
		frappe.db.commit()
		try:
			report = inspect_file(path, artifact.media_type, scene, policy, artifact.name)
		except Exception as exc:
			report = {"status": "Not Checked", "results": [], "error": str(exc)[:600]}
		from joymedia.services.workflows.capabilities import controls

		can_reroll = "source_frame_hold" not in controls(frappe.get_doc("Generation Workflow", job.workflow))
		report.update(
			source_sha256=content_hash,
			snapshot_sha256=snapshot_hash,
			policy=policy,
			quality_retryable=can_reroll,
			attempt=attempt.name,
			artifact=artifact.name,
		)
		# Result polling uses this same lock. Hold it only for the final writes,
		# never while waiting for the remote visual judge.
		with filelock(f"joymedia-sync-attempt-{attempt_name}"):
			frappe.db.commit()
			attempt.reload()
			run.reload()
			job.reload()
			if (
				attempt.status not in {"Running", "Queued"}
				or job.status in {"Cancelled", "Failed"}
				or run.status in {"Cancelled", "Failed"}
			):
				return
			store_report(attempt, artifact, report)
			frappe.db.commit()
			attempt.reload()
			_complete_attempt(
				attempt,
				history,
				artifact,
				frappe.get_doc("Generation Artifact", last_frame_name) if last_frame_name else None,
			)
			frappe.db.commit()


def quality_retry(attempt):
	"""Only witnessed violations get a bounded stochastic retry. Unknowns stop."""
	report = report_for(attempt.name)
	if not report or report.get("status") != "Needs Review" or report.get("quality_retryable") is False:
		return False
	results = report.get("results") or []
	return bool(results) and any(r.get("verdict") == "violated" for r in results)


def retry_prompt(attempt, original):
	if attempt.retry_reason != "QA Rejection" or not attempt.retry_of:
		return original
	report = report_for(attempt.retry_of) or {}
	failed = [r["claim"] for r in report.get("results", []) if r.get("verdict") == "violated"]
	if not failed:
		raise ValueError("A quality retry requires frozen rejection evidence.")
	# Use authored claims, never free-form judge suggestions as instructions.
	return (
		original
		+ "\nCorrection constraints (same action, cast, references and timing):\n"
		+ "\n".join(f"- {c}" for c in failed)
	)


def screen_composition(path, run_name, shot_name, artifact_name):
	"""Check after source overlays too: source fidelity alone does not prove support.

	This is finalization, so never reroll a provider to repair editorial geometry.
	Keep the provider artifact and report and stop selection on missing evidence.
	"""
	from frappe.utils.file_manager import save_file

	run = frappe.get_doc("Generation Run", run_name)
	snapshot = frappe.parse_json(run.project_snapshot_json or "{}") or {}
	policy = snapshot.get("visual_admission")
	if not policy:
		return
	if policy.get("version") != VERSION or policy.get("implementation_sha256") != implementation_hash():
		raise ValueError(
			"Final visual admission implementation differs from this frozen run. Regenerate with the current policy."
		)
	scene = next(s for s in snapshot["shots"] if s["shot"] == shot_name)
	try:
		report = inspect_file(path, "Video", scene, policy, artifact_name)
	except Exception as exc:
		report = {"status": "Not Checked", "error": str(exc)[:600]}
	report.update(
		stage="composition",
		source_sha256=digest(Path(path).read_bytes()),
		snapshot_sha256=digest(run.project_snapshot_json.encode()),
		policy=policy,
	)
	payload = json.dumps(report, ensure_ascii=False, sort_keys=True).encode()
	save_file(
		f"{run_name}-{shot_name}-composition-{digest(payload)[:16]}.json",
		payload,
		"Generation Artifact",
		artifact_name,
		is_private=1,
	)
	if report["status"] != "Passed" and not report.get("review_only"):
		raise ValueError(
			"Final visual admission held this composition; inspect its saved evidence. The previous selected take is preserved."
		)
	return not report.get("review_only")


def precheck_image(attempt, artifact, content):
	"""Reject a witnessed unwanted actor before expensive source preparation.

	Native pixels remain the diagnostic primary image of the rejected attempt.
	Only a definite positive observation short-circuits; all other images still
	require source preparation and the full asynchronous admission pass.
	"""
	from joymedia.services.review.consistency import OUTSIDER, ask

	_job, run, scene, policy = context_for(attempt)
	if not policy or not any(c["id"] == "unrequested_human" for c in screening_claims(scene, False)):
		return None
	try:
		answer = ask(content, OUTSIDER, configured=frappe._dict(policy["judge"]))
	except Exception:
		return None  # full admission remains mandatory and fails closed
	if (
		answer.get("answer") is not True
		or not isinstance(answer.get("reason"), str)
		or not answer["reason"].strip()
	):
		return None
	return dict(
		status="Needs Review",
		stage="native_image",
		source_sha256=digest(content),
		snapshot_sha256=digest(run.project_snapshot_json.encode()),
		policy=policy,
		attempt=attempt.name,
		artifact=artifact.name,
		quality_retryable=True,
		results=[
			dict(
				id="unrequested_human",
				dimension="cast",
				verdict="violated",
				frames=[0],
				claim="No unrequested human body part is physically present.",
				reason=answer["reason"][:500],
			)
		],
		samples=[dict(index=0, frame_index=0, time=0, sha256=digest(content))],
		presence_observations=[dict(frame=0, present=True, reason=answer["reason"][:500])],
	)
