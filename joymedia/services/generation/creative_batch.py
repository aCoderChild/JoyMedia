"""Durable orchestration over the existing workbook, generation and finishing jobs.

Batch completion means a review export. Existing identity, physical evidence,
candidate selection and release gates are never silently overridden.
"""

import copy
import time
import uuid

import frappe
from frappe.utils.background_jobs import get_queue, get_queues_timeout, get_workers
from redis.exceptions import LockError

from joymedia.services.generation.automation import advance_automatic_run, delivery_context, is_automatic
from joymedia.services.generation.availability import partner_batch_waits_for_gpu
from joymedia.services.project.render_queue import is_render_alive
from joymedia.services.workflows.pipeline import persist_execution_pin, pinned_execution


def _write(batch, variants, status=None, error="", changed_index=None):
	# Merge only the changed variant so planning and native render polling cannot
	# overwrite one another. Inference runs outside this short admission lock.
	with frappe.cache.lock(f"joymedia-creative:{batch}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		current = frappe.get_doc("Creative Batch", batch)
		if current.status == "Cancelled":
			return False
		if changed_index is not None:
			latest = frappe.parse_json(current.variants_json)
			latest[changed_index] = variants[changed_index]
			variants = latest
		states = {v["status"] for v in variants}
		if status is None:
			status = (
				"Completed"
				if states == {"Completed"}
				else "Scripts Ready"
				if states <= {"Script Ready", "Completed"}
				else "Planning"
				if states & {"Queued", "Planning", "Rewriting"}
				else "Rendering"
				if states & {"Locations", "Keyframes", "Rendering"}
				else "Finishing"
				if states & {"Finishing", "Exporting"}
				else "Awaiting Review"
				if states <= {"Pictures Ready", "Script Ready", "Completed"}
				else "Needs Attention"
			)
		frappe.db.set_value(
			"Creative Batch",
			{"name": batch, "status": ["!=", "Cancelled"]},
			{
				"variants_json": frappe.as_json(variants),
				"status": status,
				"error": error,
			},
			update_modified=True,
		)
		frappe.db.commit()
		return True


AUTOMATIC_PICTURE_REDRAWS = 3
# A screenplay which the Director has explicitly marked incomplete must never
# consume GPU work. Give the writer two new, grounded concepts before the
# normal failure path records the evidence. This is intentionally separate
# from the six in-context repairs in ``draft_script``: a fresh variation ID
# prevents the planner cache from returning the same rejected proposal.
AUTOMATIC_SCRIPT_REDRAWS = 4
PLANNING_JOB_TIMEOUT = 10800  # Multi-pose preparation can run several GPU jobs.
# Before a whole new concept, rewrite only the scenes whose drawn first frame
# failed a clear check (ViMax/Idea2Img-style targeted repair): passing scenes
# keep their pictures and a failed staging is corrected with its own evidence.
AUTOMATIC_SCENE_REWRITES = 2
# A failed pose-generation pass is evidence about the available visual inputs.
# Give the writer one chance to stage the same story with verified body states.
AUTOMATIC_POSE_SCRIPT_REDRAWS = 1
# A defect is repaired where it was caused. What the picture model drew wrong
# (medium, an extra hand, extra packs, a full body in a detail) is corrected in
# that frame's own prompt and redrawn; a staging error goes to a scene rewrite.
FRAME_CORRECTIONS = (
	"Critical geometry:",
	"Critical identity:",
	"Critical style:",
	"human hand",
	"product packages are drawn",
	"full character body appears in a close",
	"the cast appears twice",
)
AUTOMATIC_FRAME_CORRECTIONS = 2
# The GPU product lock rejects a frame whose pack outline differs from the
# source photo's proportions, or that shows a second pack. A new seed rarely
# fixes that; the frame's prompt must say how the one pack sits.
PRODUCT_VIEW_FAILURES = (
	"Expected one unambiguous product; detected ",
	"Product view is incompatible with the supplied source photograph.",
	"Product is cropped at the scene edge.",
	"Original source cannot fit the detected footprint.",
)
PLANNING_QUEUE = "joymedia_planning"


class UnverifiedPoseRequirements(ValueError):
	"""A scripted opening pose has no qualified image to bind to the shot."""


def _require_verified_pose_views(views):
	unverified = [row for row in views or [] if row.get("status") != "ready" and row.get("scene")]
	missing = sorted({int(row["scene"]) for row in unverified})
	if missing:
		requirements = list(
			dict.fromkeys(str(row.get("pose") or "").strip()[:140] for row in unverified if row.get("pose"))
		)[:3]
		raise UnverifiedPoseRequirements(
			"Required character pose references could not be verified for scenes "
			+ ", ".join(map(str, missing))
			+ (". Required body state: " + "; ".join(requirements) if requirements else "")
			+ ". First-frame rendering is stopped until a matching pose passes identity and physical checks."
		)


def _admit_pose_preparation(variant):
	"""Do not turn a failed reusable pose into a rendered character reference."""
	_require_verified_pose_views(variant.get("pose_views"))


def _pose_transition_defects(script, pose_views):
	"""Check the scene sequence against the poses actually selected for it."""
	import re

	from joymedia.services.planning.pose_coverage import STAND_UP, source_pose_state

	sit_down = re.compile(
		r"\b(?:sit(?:s|ting)?\s+down|takes?\s+(?:a\s+)?seat|settles?\s+into\s+(?:a\s+)?seat)\b", re.I
	)
	last = {}
	defects = []
	for row in sorted(pose_views or [], key=lambda item: int(item.get("scene") or 0)):
		index = int(row.get("scene") or 0) - 1
		if index < 0 or index >= len(script.get("scenes") or []):
			continue
		identity = row.get("source")
		state = source_pose_state([row.get("pose")])
		if not identity or state not in {"seated_supported", "mobile_or_upright"}:
			continue
		previous = last.get(identity)
		if previous and previous[0] == index and previous[1] != state:
			action = str(script["scenes"][index - 1].get("action") or "")
			transition = STAND_UP.search(action) if state == "mobile_or_upright" else sit_down.search(action)
			if not transition:
				defects.append(
					f"Scene {index + 1} changes {identity} from {previous[1]} to {state} "
					"without a visible transition in the preceding scene."
				)
		last[identity] = (index + 1, state)
	return defects


def _admit_revised_pose_preparation(variant, script):
	"""Apply the same pose and continuity gates before importing a revision."""
	_admit_pose_preparation(variant)
	defects = _pose_transition_defects(script, variant.get("pose_views"))
	if defects:
		raise ValueError("Revised script retained an unsupported body transition: " + defects[0])


def _restart_script_after_pose_shortfall(variant):
	"""Replan once from observed pose coverage before admitting any first frame."""
	if int(variant.get("pose_script_redraws") or 0) >= AUTOMATIC_POSE_SCRIPT_REDRAWS:
		return False
	script = variant.get("script") or {}
	missing = [row for row in variant.get("pose_views") or [] if row.get("status") != "ready"]
	if not script or not missing:
		return False
	failed = ", ".join(str(row.get("scene")) for row in missing if row.get("scene"))
	# Give the writer concrete, qualified alternatives. A generic request to
	# "use an available pose" previously produced the same unsupported seated
	# state on every redraw, even when an upright free-paw view was available.
	available = []
	project_name = variant.get("project")
	if project_name and frappe.db.exists("Media Project", project_name):
		from joymedia.services.planning.pose_assets import _qualified_pose_metadata

		project = frappe.get_doc("Media Project", project_name)
		for row in project.get("selected_media") or []:
			if str(row.get("reference_role") or "").casefold() not in {"character", "person"}:
				continue
			analysis = (
				frappe.parse_json(
					frappe.db.get_value("Asset Version", row.asset_version, "analysis_json") or "{}"
				)
				or {}
			)
			qualified = _qualified_pose_metadata(analysis)
			if qualified:
				option = (
					row.get("identity_key") or row.get("reference_key"),
					qualified["pose"],
					qualified.get("view") or "front",
				)
				if option not in available:
					available.append(option)
	pose_options = "; ".join(
		f"identity {identity}: {pose} ({view} view)" for identity, pose, view in available[:12]
	)
	if not _restart_automatic_script_variant(
		variant,
		script,
		[
			"The first-frame pose preparation could not verify the opening body states "
			f"for scenes {failed}. Re-stage those scenes using body state, orientation and "
			"support already visible in supplied or qualified character references. "
			+ (
				f"The verified alternatives are: {pose_options}. "
				if pose_options
				else "No alternate character pose has been verified. "
			)
			+ "Rewrite the opening composition AND action so they agree with one of these "
			"states; do not keep an unsupported seated or free-paw state merely by "
			"changing its name. Preserve any client-mandated body state; if no verified "
			"state can support that interaction, use a separate, physically supported "
			"product shot and keep the character in a source-faithful cutaway. "
			"Keep a complete product interaction and its cause-before-effect order; "
			"change the camera framing or object action where needed. Do not label an "
			"unverified generated pose as a qualified reference."
		],
		extra_budget=AUTOMATIC_POSE_SCRIPT_REDRAWS,
		allow_character_cutaway=True,
	):
		return False
	variant["pose_script_redraws"] = int(variant.get("pose_script_redraws") or 0) + 1
	# A new screenplay has new requirements. Re-evaluate both media preparation
	# stages instead of reusing their completion flags from the rejected script.
	for key in ("pose_prepared", "pose_views", "product_views_prepared", "product_views", "product_cutouts"):
		variant.pop(key, None)
	return True


def _automatic_script_defects(script):
	"""Keep review advice visible without deadlocking a valid automatic script.

	``draft_script`` has already exhausted its bounded rewrites and validated the
	returned fallback. Subjective Director notes are not reliable hard failures:
	they can contradict the visible cause order, as observed on Shera Video 49.
	"""
	if (script.get("writer_fallback") or {}).get("quality_review") == "deferred":
		return []
	defects = [str(note).strip() for note in script.get("director_notes") or [] if str(note).strip()]
	if script.get("writer_fallback") and not defects:
		defects.append("The writer retained a fallback draft without resolving its quality review.")
	return list(dict.fromkeys(defects))


def _blocking_script_defects(script):
	"""Return unresolved causal or physical screenplay defects.

	The Director's prose notes can be subjective, but its structured action review
	identifies a missing prerequisite or a direct brief contradiction.  Those are
	not safe inputs for a pose library or a first-frame model: a correct character
	pose cannot make an impossible action chain coherent.
	"""
	# A structurally valid fallback is not proof of physical causality. Keep
	# unresolved structured findings as blockers even when optional review was
	# deferred; retracted findings have already been reclassified by the reviewer.
	blocking = {"missing_prerequisite", "brief_contradiction", "missing_contact_or_result"}
	issues = (script.get("action_review") or {}).get("issues") or []
	return list(
		dict.fromkeys(
			str(issue.get("instruction") or issue.get("quote") or "").strip()
			for issue in issues
			if issue.get("category") in blocking
			and str(issue.get("instruction") or issue.get("quote") or "").strip()
		)
	)


def _critical_frame_defects(shots):
	"""Escalate repeated clear visual failures to a new concept before H3 time."""
	failed = []
	material_failure = False
	for shot in shots:
		if shot.consistency_status != "Needs Review":
			continue
		critical = [
			part.strip()
			for part in str(shot.consistency_notes or "").split("; ")
			if part.strip().startswith(
				("Critical geometry:", "Critical identity:", "Critical framing:", "Critical prop:")
			)
		]
		if critical:
			failed.append(f"Scene {shot.shot_number}: {critical[0][:260]}")
			material_failure |= any("implausible material" in item.lower() for item in critical)
	# A single plainly wrong hero material invalidates the product demonstration;
	# most other vision findings require corroboration across two scenes.
	return failed if material_failure or len(failed) >= 2 else []


def _critical_findings(shot):
	return [
		part.strip()
		for part in str(shot.consistency_notes or "").split("; ")
		if part.strip().startswith(
			(
				"Critical geometry:",
				"Critical identity:",
				"Critical framing:",
				"Critical prop:",
				"Critical style:",
			)
		)
	]


def _frame_corrections(shots):
	"""{shot name: correction sentences} for defects the picture model can fix in a redraw."""
	corrections = {}
	for shot in shots:
		if shot.consistency_status != "Needs Review":
			continue
		findings = _critical_findings(shot)
		if any("stale or missing pose qualification" in finding for finding in findings):
			# No image-seed or prompt change can certify an invalid input asset.
			# Replan the scene from verified source media instead.
			continue
		found = [finding for finding in findings if any(marker in finding for marker in FRAME_CORRECTIONS)]
		if found:
			corrections[shot.name] = found
	return corrections


def _scene_repair_notes(shots):
	"""One rewrite note per scene whose first frame still shows a staging error (support, contact, size, rules)."""
	notes = []
	for shot in shots:
		if shot.consistency_status != "Needs Review":
			continue
		critical = [
			finding
			for finding in _critical_findings(shot)
			# Geometry gets a cheap evidence-directed redraw first. If both
			# redraws fail, it still needs a change to the scene staging.
			if finding.startswith(("Critical geometry:", "Critical identity:"))
			or not any(marker in finding for marker in FRAME_CORRECTIONS)
		]
		if critical:
			critical.sort(key=lambda finding: 0 if "stale or missing pose qualification" in finding else 1)
			unqualified_pose = "stale or missing pose qualification" in critical[0]
			notes.append(
				{
					"scene": int(shot.shot_number),
					"text": (
						"The drawn first frame of this scene failed an automatic check: "
						+ critical[0][:400]
						+ (
							". Select an opening body state supported by a verified character reference, "
							"or prepare a newly qualified pose before drawing. Never reuse an unqualified pose. "
							if unqualified_pose
							else ". Restage only this scene so the error cannot occur. Preserve the authored pose and support. "
						)
						+ "If the actor is seated on the floor, keep its entire body on the floor rather "
						"than adding a chair. Move furniture far enough away that it cannot divide or support the "
						"actor. Keep the intended interaction reachable, the supplied cast in its reference look, "
						"and each advertised product on its own support. Preserve the scene's purpose and timing."
					),
				}
			)
	return notes


def _audit_rejected_first_frames(project, shots, run_name, audited):
	"""Give the scene repairer visible evidence from images rejected before selection.

	Visual admission can fail a generated candidate before it becomes a Shot
	keyframe. Without this bridge the repair ladder sees no image or finding and
	can only reroll the same inputs. Audit the latest rejected picture once per
	artifact, using the same physical reviewer as selected first frames.
	"""
	if not run_name:
		return []
	from joymedia.services.review.physical_audit import frame_findings

	marked = []
	for shot in shots:
		if shot.keyframe_artifact or shot.consistency_status in {"Checking", "Redrawing"}:
			continue
		rows = frappe.db.sql(
			"""select g.name, g.frappe_file from `tabGeneration Artifact` g
			join `tabGeneration Attempt` a on a.name = g.generation_attempt
			join `tabGeneration Task` t on t.name = a.generation_task
			where t.generation_run = %s and t.shot = %s
			and a.status = 'Failed' and g.artifact_role = 'Primary Image'
			order by a.creation desc, g.creation desc limit 1""",
			(run_name, shot.name),
			as_dict=True,
		)
		if not rows or audited.get(shot.name) == rows[0].name:
			continue
		try:
			issues = frame_findings(project, frappe.get_doc("Shot", shot.name), rows[0].frappe_file)
		except Exception:
			frappe.log_error(title=f"Rejected first-frame audit deferred for {shot.name}")
			continue
		audited[shot.name] = rows[0].name
		if not issues:
			continue
		notes = "; ".join(issues)[:1000]
		frappe.db.set_value(
			"Shot",
			shot.name,
			{
				"consistency_status": "Needs Review",
				"consistency_notes": notes,
			},
			update_modified=False,
		)
		shot.consistency_status = "Needs Review"
		shot.consistency_notes = notes
		marked.append(shot.name)
	return marked


def _redraws_exhausted(shot_name):
	"""Stop redrawing a frame whose recent first-frame tasks all failed without a picture.

	Mirrors the consistency worker's bound: a redraw that is rejected before it
	produces an artifact never reaches a check, so its status would stay
	"Redrawing" and occupy the GPU forever. The shot keeps its findings for review.
	"""
	recent = frappe.get_all(
		"Generation Task",
		filters={"shot": shot_name},
		fields=["status"],
		order_by="creation desc",
		limit_page_length=AUTOMATIC_PICTURE_REDRAWS,
	)
	if len(recent) < AUTOMATIC_PICTURE_REDRAWS or any(row.status != "Failed" for row in recent):
		return False
	frappe.db.set_value("Shot", shot_name, "consistency_status", "Needs Review", update_modified=False)
	return True


def _product_lock_rejected(run_name, shot_name):
	"""True when the scene's latest first-frame attempt in this run failed the GPU product lock."""
	if not run_name:
		return False
	task = frappe.db.get_value("Generation Task", {"generation_run": run_name, "shot": shot_name}, "name")
	latest = (
		frappe.get_all(
			"Generation Attempt",
			filters={"generation_task": task},
			fields=["status", "error_details"],
			order_by="creation desc",
			limit_page_length=1,
		)
		if task
		else []
	)
	return bool(
		latest
		and latest[0].status == "Failed"
		and any(cause in (latest[0].error_details or "") for cause in PRODUCT_VIEW_FAILURES)
	)


def _mark_for_corrected_redraw(shot_name, findings):
	"""Queue a frame redraw whose prompt gets a retry correction for these findings.

	The finding travels as the shot's retry note (``keyframe_retry_note`` in the
	run snapshot, read by ``prompts._keyframe_retry_direction``), so it reaches
	the still-image prompt only; the scene's own direction, which the opening
	check verifies, is never edited.
	"""
	frappe.db.set_value(
		"Shot",
		shot_name,
		{"consistency_status": "Redrawing", "consistency_notes": "; ".join(findings)[:1000]},
		update_modified=False,
	)


def _correct_product_views(run_name, shot_names):
	"""Before redrawing frames the product lock rejected, give each one its rejection as a retry correction."""
	if not run_name or not shot_names:
		return []
	corrected = []
	for task in frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name, "shot": ["in", list(shot_names)]},
		fields=["name", "shot"],
	):
		latest = frappe.get_all(
			"Generation Attempt",
			filters={"generation_task": task.name},
			fields=["status", "error_details"],
			order_by="creation desc",
			limit_page_length=1,
		)
		cause = next(
			(
				cause
				for cause in PRODUCT_VIEW_FAILURES
				if latest and latest[0].status == "Failed" and cause in (latest[0].error_details or "")
			),
			None,
		)
		if cause:
			_mark_for_corrected_redraw(task.shot, [f"Product lock: {cause.strip()}"])
			corrected.append(task.shot)
	return corrected


def _seal_automatic_plan(project_name):
	"""Re-approve the plan an automatic batch is about to draw or render.

	Drawing pictures legitimately refines the storyboard (places, a check's retry
	direction, a frame correction). The batch request already authorizes automatic
	delivery, so the batch seals that plan as a reviewer would, instead of stopping
	with "the storyboard changed after it was approved".
	"""
	from joymedia.services.planning.signature import compute_plan_signature

	frappe.db.set_value(
		"Media Project",
		project_name,
		{
			"approved_plan_signature": compute_plan_signature(project_name),
			"storyboard_approval_status": "Approved",
		},
		update_modified=False,
	)


def _start_frame_corrections(batch, variants, index, project, corrections):
	"""Add each correction to its frame's prompt and redraw only those frames, within the budget."""
	from joymedia.services.keyframes.stage import generate_keyframes

	variant = variants[index]
	if variant.get("repairs_exhausted"):
		return False
	used = variant.setdefault("frame_corrections", {})
	wanted = [name for name in corrections if int(used.get(name) or 0) < AUTOMATIC_FRAME_CORRECTIONS]
	if not wanted:
		return False
	request = frappe.parse_json(batch.request_json)
	with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
			return True
		for name in wanted:
			_mark_for_corrected_redraw(name, corrections[name])
			used[name] = int(used.get(name) or 0) + 1
		_seal_automatic_plan(project.name)
		with (
			pinned_execution(project.name, project.generation_pipeline),
			delivery_context(request, batch.name),
		):
			variant["keyframe_request"] = generate_keyframes(
				project.name, sorted(wanted), draw_places=False, automatic=True
			)
		frappe.db.commit()
	_write(batch.name, variants, changed_index=index)
	return True


def _start_automatic_scene_repair(batch_name, variants, index, notes):
	"""Queue an in-place rewrite of the failing scenes, within the repair budget."""
	variant = variants[index]
	rounds = int(variant.get("automatic_scene_rewrites") or 0)
	if not notes or rounds >= AUTOMATIC_SCENE_REWRITES:
		return False
	variant.setdefault("history", []).append(
		{
			k: copy.deepcopy(variant.get(k))
			for k in ("project", "workbook", "script", "title")
			if variant.get(k)
		}
	)
	variant.update(
		scene_revision={"notes": notes, "by": "Automatic quality gate"},
		automatic_scene_rewrites=rounds + 1,
		status="Rewriting",
	)
	_write(batch_name, variants, changed_index=index)
	frappe.enqueue(
		"joymedia.services.generation.creative_batch.rewrite_scenes_in_place",
		queue=_planning_queue(),
		timeout=3600,
		batch_name=batch_name,
		position=index,
		job_id=f"joymedia-creative-rewrite:{batch_name}:{index}",
		deduplicate=True,
		enqueue_after_commit=True,
	)
	frappe.db.commit()
	return True


def _restart_automatic_script_variant(
	variant, script, defects, *, extra_budget=0, allow_character_cutaway=False
):
	"""Reset a pre-render variant for an autonomous screenplay rewrite.

	The old child project and script remain in the variant history for audit. A
	new child receives the same immutable references, so no generated keyframe or
	video can leak from a rejected concept into its replacement.
	"""
	redraws = int(variant.get("automatic_script_redraws") or 0)
	if redraws >= AUTOMATIC_SCRIPT_REDRAWS + extra_budget:
		return False
	history = {
		k: copy.deepcopy(variant.get(k)) for k in ("project", "workbook", "script", "title") if variant.get(k)
	}
	# The rejected screenplay has not been assigned to ``variant['script']``
	# yet; preserve it explicitly so the Director's redraw is auditable.
	history["script"] = copy.deepcopy(script)
	variant.setdefault("history", []).append(history)
	# A rejected text-only proposal has not changed the child project. Reuse its
	# number and references; make a new child only after a workbook or visual job
	# has been persisted, where old media could contaminate the replacement.
	reuse_empty_project = bool(
		variant.get("project")
		and not any(variant.get(key) for key in ("workbook", "keyframe_request", "generation_request"))
	)
	shot_requirement = (
		"A source-faithful character cutaway may be static when required poses cannot be verified; "
		"put the product interaction in another physically supported shot while preserving the requested story. "
		if allow_character_cutaway
		else "Every non-final shot must complete an object or material interaction; keep smiles and gestures as brief reactions after that interaction, never as a standalone shot."
	)
	notes = [
		{
			"scene": None,
			"text": (
				"Automatic quality gate: the previous screenplay cannot be rendered. "
				"The findings below are diagnoses, not approved replacement directions; ignore any suggested new action that conflicts with supplied references, the client's avoid rules, or visible cause-before-effect order. "
				"Replace the unsafe or incomplete action chain with direct, supported product handling. "
				"Do not invent water, spills, cleaning effects, unsupported travel, or an action whose prerequisite is not visible. An effect explicitly required by the client's mandatories and supported by approved claims is allowed: show its cause, contact and gradual visible result. "
				+ shot_requirement
			),
		}
	]
	notes.extend({"scene": None, "text": defect} for defect in defects)
	if any("no completed object or material action" in defect for defect in defects):
		notes.append(
			{
				"scene": None,
				"text": (
					"For each reaction-only shot, replace the action itself: first finish placing any held used material on a support; then visibly orient, lift or place the featured product for presentation. React only after that completed interaction. Update the opening image, cast and product keys to match the new action. A smile, nod, look or thumbs-up alone does not satisfy this shot."
				),
			}
		)
	variant["revision"] = {"script": copy.deepcopy(script), "notes": notes, "by": "Automatic quality gate"}
	for key in (
		"project",
		"workbook",
		"script",
		"title",
		"plans",
		"error",
		"resume_stage",
		"location_job",
		"keyframe_request",
		"generation_request",
		"picture_notes",
		"auto_redraws",
		"frame_authorization",
		# A new concept has new scenes: its targeted repairs start with a full budget.
		"automatic_scene_rewrites",
		"frame_corrections",
		"physical_audit",
		"scene_revision",
		"pose_prepared",
		"pose_views",
		"product_views_prepared",
		"product_views",
		"product_cutouts",
	):
		if key == "project" and reuse_empty_project:
			continue
		variant.pop(key, None)
	variant.update(
		nonce=uuid.uuid4().hex,
		automatic_script_redraws=redraws + 1,
		status="Queued",
	)
	return True


def _stale_keyframe(shot_name):
	"""True when a drawn frame no longer matches the scene it was drawn from.

	A scene rewrite changes that shot's direction. If its redraw then fails, the
	previous picture survives with the previous signature, and approval correctly
	refuses it. The batch must redraw such a frame rather than stop the video.
	"""
	from joymedia.services.keyframes.stage import keyframe_signature

	shot = frappe.get_doc("Shot", shot_name)
	return bool(shot.keyframe_artifact) and shot.keyframe_signature != keyframe_signature(shot)


def _nonretryable_scene_failure(run_name, shot_names):
	"""Return a grounded blocker before an automatic rerender of unchanged inputs."""
	from joymedia.services.generation.failures import classify_failure

	if not run_name or not shot_names:
		return None
	for task in frappe.get_all(
		"Generation Task",
		filters={"generation_run": run_name, "shot": ["in", list(shot_names)]},
		fields=["name", "shot"],
	):
		latest = frappe.get_all(
			"Generation Attempt",
			filters={"generation_task": task.name},
			fields=["status", "failure_class", "error_summary", "error_details"],
			order_by="creation desc",
			limit_page_length=1,
		)
		if (
			latest
			and latest[0].status == "Failed"
			and latest[0].failure_class == "Input"
			and any(cause in (latest[0].error_details or "") for cause in PRODUCT_VIEW_FAILURES)
		):
			# The source is valid; a stochastic scene image contained extra
			# packages. A new first-frame seed can fix that without changing input.
			continue
		# An execution interrupted on the GPU was once labelled a workflow defect;
		# its recorded evidence shows it only needs another render.
		if latest and classify_failure(latest[0].error_details, latest[0].failure_class) == "Infrastructure":
			continue
		if latest and latest[0].status == "Failed" and latest[0].failure_class in {"Input", "Workflow"}:
			return {
				"shot": task.shot,
				"failure_class": latest[0].failure_class,
				"reason": latest[0].error_summary,
			}
	return None


def _planning_queue():
	"""Keep slow script writing off the worker that advances render jobs."""
	if PLANNING_QUEUE in get_queues_timeout() and get_workers(get_queue(PLANNING_QUEUE)):
		return PLANNING_QUEUE
	return "long"


def _active_variant_limit():
	try:
		return max(1, int(frappe.conf.get("joymedia_active_variants_per_batch", 2)))
	except (TypeError, ValueError):
		return 2


def _visual_slots_used(variants):
	return sum(
		variant["status"] in {"Planning", "Locations", "Keyframes", "Rendering", "Finishing", "Exporting"}
		for variant in variants
	)


def _next_prepare_index(variants):
	# Resume a partially prepared video before admitting a new one. This also
	# avoids stranding a Planning row behind an earlier Queued row at capacity.
	index = next((i for i, variant in enumerate(variants) if variant["status"] == "Planning"), None)
	if index is not None:
		return index
	if _visual_slots_used(variants) >= _active_variant_limit():
		return None
	return next(
		(
			i
			for i, variant in enumerate(variants)
			if variant["status"] == "Queued" and float(variant.get("retry_after") or 0) <= time.time()
		),
		None,
	)


def _prepare_position(variants, position):
	if position is None:
		return _next_prepare_index(variants)  # historical queued jobs
	if type(position) is not int or not 0 <= position < len(variants):
		return None
	status = variants[position]["status"]
	if status == "Planning" or (
		status == "Queued"
		and float(variants[position].get("retry_after") or 0) <= time.time()
		and _visual_slots_used(variants) < _active_variant_limit()
	):
		return position
	return None


def _transient(exc):
	# MariaDB's optimistic-read conflict is emitted by either MySQLdb or
	# PyMySQL, depending on the worker connection. Frappe's helpers recognize
	# deadlocks/timeouts but need not classify ER_CHECKREAD (1020).
	args = getattr(exc, "args", ()) or ()
	series_conflict = bool(args and args[0] == 1020) or (
		"1020" in str(exc) and "Record has changed since last read" in str(exc)
	)
	# A duplicate scheduler/planner handoff can reach storyboard approval just
	# after the first-frame run is queued. Its busy-scene guard is correct, but
	# the batch should wait for that run rather than ask the user to retry it.
	busy_scene = "This scene is still being rendered. Please wait until it is ready." in str(exc)
	# The remote GPU's network link drops briefly; the next scheduler tick tries again
	# instead of stopping an automatic video for something no person can fix.
	render_link = "Unable to connect to ComfyUI" in str(exc)
	return (
		frappe.db.is_deadlocked(exc)
		or frappe.db.is_timedout(exc)
		or series_conflict
		or busy_scene
		or render_link
	)


def _defer_planner_outage(variant, exc):
	"""Keep a references-only script queued until its text service returns.

	No nonce or creative retry budget is consumed: the model never returned a
	proposal. The scheduler checks the deadline and submits this same variant.
	"""
	from joymedia.services.planning.production import PlannerUnavailableError

	if not isinstance(exc, PlannerUnavailableError):
		return False
	attempts = int(variant.get("planner_outage_attempts") or 0) + 1
	variant.update(
		status="Queued",
		resume_stage="Planning",
		error=str(exc)[:1600],
		planner_outage_attempts=attempts,
		retry_after=time.time() + min(60 * 2 ** min(attempts - 1, 5), 1800),
	)
	return True


def _defer_reference_analysis(variant, exc):
	"""Retry failed image analysis with a bounded budget and preserve the same video."""
	from joymedia.services.planning.creative import ReferenceAnalysisUnavailable

	if not isinstance(exc, ReferenceAnalysisUnavailable):
		return False
	attempts = int(variant.get("reference_analysis_attempts") or 0) + 1
	variant["reference_analysis_attempts"] = attempts
	if attempts >= 3:
		return False
	variant.update(
		status="Queued",
		resume_stage="Planning",
		error=str(exc)[:1600],
		retry_after=time.time() + 60 * attempts,
	)
	return True


def _defer_lost_comfy_job(variant, exc):
	"""Resume preparation when a submitted GPU job disappeared after a restart."""
	from joymedia.services.workflows.comfyui import ComfyJobLostError

	if not isinstance(exc, ComfyJobLostError):
		return False
	attempts = int(variant.get("lost_comfy_attempts") or 0) + 1
	variant["lost_comfy_attempts"] = attempts
	if attempts >= 3:
		return False
	variant.update(
		status="Queued",
		resume_stage="Planning",
		error=str(exc)[:1600],
		retry_after=time.time() + 30 * attempts,
	)
	return True


def _finish_previous_concept(variant):
	"""When even the last concept cannot be written, finish the newest earlier one that reached pictures.

	Every earlier concept passed the screenplay checks and was drawn; it was replaced
	only because some frames failed. Delivering it with those scenes flagged is better
	than an automatic order that ends with nothing.
	"""
	for entry in reversed(variant.get("history") or []):
		project = entry.get("project")
		if not (project and entry.get("script") and frappe.db.exists("Media Project", project)):
			continue
		if not frappe.db.exists("Shot", {"media_project": project, "keyframe_artifact": ["is", "set"]}):
			continue
		variant.update(
			project=project,
			workbook=entry.get("workbook"),
			script=entry["script"],
			title=entry.get("title") or variant.get("title"),
			status="Keyframes",
			error="",
			repairs_exhausted=True,
			automatic_scene_rewrites=AUTOMATIC_SCENE_REWRITES,
		)
		variant.pop("resume_stage", None)
		return True
	return False


def _redraw_invalid_automatic_script(variant, exc):
	"""Give an invalid screenplay a fresh concept, then retain the best safe draft.

	A screenplay is generated before either assisted or fully automatic delivery,
	so a bounded text-only retry must not turn either mode into a manual blocker.
	After bounded clean rewrites, run the writer once more in
	structured-fallback mode: hard schema/physics checks still apply, while
	conflicting advisory notes are preserved on the screenplay for later QA.
	"""
	if not str(exc).startswith(
		(
			"Automatic script remained invalid after bounded repair:",
			"Automatic screenplay quality retries exhausted",
			"The planner returned invalid JSON after retry:",
		)
	):
		return False
	redraws = int(variant.get("automatic_script_redraws") or 0)
	if redraws >= AUTOMATIC_SCRIPT_REDRAWS:
		if variant.get("accept_advisory_fallback"):
			return _finish_previous_concept(variant)
		variant.setdefault("script_attempts", []).append(
			{"nonce": variant.get("nonce"), "error": str(exc)[:3000]}
		)
		variant.update(
			nonce=uuid.uuid4().hex,
			accept_advisory_fallback=True,
			status="Queued",
			resume_stage="Planning",
			error="",
		)
		return True
	variant.setdefault("script_attempts", []).append(
		{"nonce": variant.get("nonce"), "error": str(exc)[:3000]}
	)
	variant.update(
		nonce=uuid.uuid4().hex,
		automatic_script_redraws=redraws + 1,
		status="Queued",
		resume_stage="Planning",
		error="",
	)
	return True


def _queue_prepare(batch_name, variants, *, replacement=False):
	# The caller may hold a stale copy after another worker advanced a video.
	batch = frappe.get_doc("Creative Batch", batch_name)
	if batch.status == "Cancelled":
		return
	if partner_batch_waits_for_gpu(batch.owner):
		return
	variants = frappe.parse_json(batch.variants_json)
	index = _next_prepare_index(variants)
	if index is None:
		return
	# A quality-gate rewrite is requested from inside the currently running
	# preparer. Reusing that job's ID makes RQ deduplicate the successor away,
	# leaving the variant indefinitely Queued after the old job exits. Give the
	# successor its new variation nonce and intentionally queue it once.
	job_id = f"joymedia-creative-prepare:{batch_name}:{index}"
	if replacement:
		job_id += ":" + str(variants[index].get("nonce") or uuid.uuid4().hex)
	if replacement or not is_render_alive(job_id):
		frappe.enqueue(
			"joymedia.services.generation.creative_batch.prepare_batch",
			queue=_planning_queue(),
			timeout=PLANNING_JOB_TIMEOUT,
			batch_name=batch_name,
			position=index,
			job_id=job_id,
			deduplicate=True,
			enqueue_after_commit=True,
		)


def _create_variant(batch, request, index, hero=None):
	from joymedia.api.projects import create_project
	from joymedia.services.project.versions import (
		copy_control_reference,
		family,
		members,
		next_video_number,
		organize_edits,
	)

	source = frappe.get_doc("Media Project", batch.source_project)
	root = family(source)
	number = next_video_number(root)
	# A variant is another video of the same project, not a project of its own.
	# Background workers commonly run as Administrator.  A newly-created project
	# must nevertheless belong to the source customer before ``organize_edits``
	# validates the family.  Creating it as the worker caused automatic batches
	# to stop at the first step with an unrelated-owner grouping error.
	active_user = frappe.session.user
	frappe.set_user(source.owner)
	try:
		project = create_project(root.project_name, request["product_name"])
	finally:
		frappe.set_user(active_user)
	project.workflow, project.generation_pipeline = request["workflow"], request["generation_pipeline"]
	for key, value in request.get("render_profile", {}).items():
		if value is not None:
			project.set(key, value)
	project.planning_mode, project.generation_mode = "Follow the sheet", "Multi-shot"
	project.total_duration_seconds = request.get("duration_seconds")
	project.delivery_width, project.delivery_height = request.get("width"), request.get("height")
	project.delivery_preset = request.get("delivery_preset")
	project.video_idea = request.get("direction") or ""
	project.storyboard_source_json = frappe.as_json({"brand": request["brand"]})
	project.soundtrack_mode = "Effects + music"
	reference_map = {}
	sheet_references = []
	for row in request["references"]:
		if (
			hero
			and row["reference_role"] == "Product"
			and (row.get("identity_key") or row["reference_key"]) != hero
		):
			# One featured product per video keeps its packaging identical in every shot.
			continue
		ref = copy.deepcopy(row)
		ref["asset_version"] = copy_control_reference(ref["asset_version"], source, project, reference_map)
		project.append("selected_media", ref)
		mode = request.get("reference_preservation_modes", {}).get(row["asset_version"])
		if mode:
			asset = frappe.get_doc("Asset Version", ref["asset_version"])
			sheet_references.append(
				{
					"name": ref["reference_key"],
					"file": frappe.get_doc("File", {"file_url": asset.file}).file_name,
					"role": ref["reference_role"],
					"preservation_mode": mode,
				}
			)
	# A newly selected original character photo may contain a removable prop or
	# only one body pose. Reuse already qualified views of that *same* source and
	# identity from the source project before asking the Director to plan shots.
	# These are generated Character references, never additional cast members.
	selected_characters = {}
	for row in request["references"]:
		if row.get("reference_role") not in {"Character", "Person"}:
			continue
		identity = row.get("identity_key") or row.get("reference_key")
		version = row.get("asset_version")
		selected_characters[(version, identity)] = reference_map.get(version, version)
		# A source edit can itself contain a copy of the original identity image.
		# Qualified views retain the original source identifier in their analysis.
		ancestor = frappe.db.get_value("Asset Version", version, "derived_from")
		if ancestor:
			selected_characters[(ancestor, identity)] = reference_map.get(version, version)
	selected_keys = {row.reference_key for row in project.selected_media}
	selected_asset_versions = {row.asset_version for row in project.selected_media if row.asset_version}
	# Pose views belong to the character identity, not to the one earlier video
	# which happened to create them.  Search the whole edit family: a new batch
	# normally starts from the root project's original upload, while a qualified
	# standing/side view may have been promoted in a previous experiment.
	# ``copy_control_reference`` preserves its immutable lineage and access rules
	# when it is brought into this fresh video.
	pose_rows = []
	for member_name in members(root):
		member = source if member_name == source.name else frappe.get_doc("Media Project", member_name)
		pose_rows.extend((member, row) for row in member.selected_media)
	for owner, row in pose_rows:
		if row.reference_role not in {"Character", "Person"}:
			continue
		if row.asset_version in selected_asset_versions:
			continue
		version = frappe.db.get_value(
			"Asset Version",
			row.asset_version,
			["analysis_status", "analysis_json", "file"],
			as_dict=True,
		)
		if not version or version.analysis_status != "Ready" or not version.file:
			continue
		analysis = frappe.parse_json(version.analysis_json or "{}") or {}
		from joymedia.services.planning.pose_assets import _qualified_pose_metadata

		qualified = _qualified_pose_metadata(analysis)
		identity = row.identity_key
		if not qualified or (qualified["source_asset_version"], identity) not in selected_characters:
			continue
		pose = qualified["pose"]
		# The same pose may already be selected by the source edit.  Prefer the
		# existing key, otherwise add an asset-derived key so every state remains
		# addressable by the Director and pose planner.
		key = row.reference_key
		if key in selected_keys:
			key = f"pose_{row.asset_version.lower()}"
		if key in selected_keys:
			continue
		cloned_version = copy_control_reference(row.asset_version, owner, project, reference_map)
		cloned_analysis = dict(analysis)
		cloned_analysis["source_asset_version"] = selected_characters[
			(analysis["source_asset_version"], row.identity_key)
		]
		# Keep a review-stable pose contract alongside the refreshed generic image
		# caption.  The latter is intentionally allowed to change as intake vision
		# improves; it must not erase evidence that made this a reusable view.
		cloned_analysis["qualified_pose_and_support"] = pose
		if analysis.get("qualified_pose_view") or analysis.get("view"):
			cloned_analysis["qualified_pose_view"] = analysis.get("qualified_pose_view") or analysis.get(
				"view"
			)
		if cloned_version != row.asset_version:
			frappe.db.set_value(
				"Asset Version",
				cloned_version,
				"analysis_json",
				frappe.as_json(cloned_analysis),
				update_modified=False,
			)
		ref = {
			"reference_key": key,
			"identity_key": identity,
			"asset_version": cloned_version,
			"reference_role": row.reference_role,
			"label": row.label,
			"relative_size": row.relative_size,
			"keep_rule": row.keep_rule,
		}
		project.append("selected_media", ref)
		selected_keys.add(key)
		selected_asset_versions.add(cloned_version)
	project.storyboard_source_json = frappe.as_json(
		{"brand": request["brand"], "references": sheet_references}
	)
	project.save(ignore_permissions=True)
	organize_edits(
		root.name,
		[{"project": project.name, "label": f"Video {number}", "kind": "Creative"}],
	)
	frappe.db.commit()
	persist_execution_pin(project.name, request["generation_pipeline"])
	return project


def _storyboard_with_frames(batch, variant, shots):
	"""Rebuild the variant's template workbook with each scene's drawn first frame."""
	from frappe.utils.file_manager import save_file

	from joymedia.services.planning.creative import script_workbook

	pictures = {}
	for shot in shots:
		control = _explicit_first_frame(shot.name)
		url = (
			frappe.db.get_value("Asset Version", control, "file")
			if control
			else shot.keyframe_artifact
			and frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
		)
		if url:
			pictures[shot.shot_number] = frappe.get_doc("File", {"file_url": url}).get_full_path()
	if not pictures:
		return
	project = frappe.get_doc("Media Project", variant["project"])
	file = save_file(
		f"{batch.name}-variant-{variant['index']}-storyboard.xlsx",
		script_workbook(variant["script"], project, pictures=pictures),
		"Media Project",
		project.name,
		is_private=1,
	)
	variant["workbook"] = file.file_url


def _name_video(project, script):
	"""Label the video by its concept and fill a product name the inputs did not give."""
	label = (project.version_label or "").split(" · ")[0]
	title = script.get("display_title") or script.get("title")
	if label.startswith("Video ") and title:
		project.db_set("version_label", f"{label} · {title}"[:100], update_modified=False)
	if script.get("product_name"):
		for name in (project.name, project.version_of):
			if name and not frappe.db.get_value("Media Project", name, "product_name"):
				frappe.db.set_value(
					"Media Project", name, "product_name", script["product_name"], update_modified=False
				)
			# Nobody should have to name a project: an untitled one takes the product's name.
			if name and frappe.db.get_value("Media Project", name, "project_name") in untitled_names():
				frappe.db.set_value(
					"Media Project", name, "project_name", script["product_name"][:140], update_modified=False
				)


def untitled_names():
	return {"Untitled Project", frappe._("Untitled Project"), "Dự án chưa đặt tên"}


def prepare_batch(batch_name, position=None):
	"""Admit one planner per video, even with several queue workers or retry jobs."""
	key = f"joymedia-creative-prepare:{batch_name}:{position}"
	try:
		# The RQ job timeout covers multi-pose GPU preparation. Duplicate jobs can otherwise plan
		# the same video concurrently. The minute scheduler requeues a variant
		# that remains Queued or Planning after a duplicate exits here.
		with frappe.cache.lock(key, timeout=PLANNING_JOB_TIMEOUT, blocking_timeout=0):
			return _prepare_batch_locked(batch_name, position)
	except LockError:
		return


def _prepare_batch_locked(batch_name, position=None):
	"""Background CPU planning. Inference never holds a database write lock."""
	from frappe.utils.file_manager import save_file

	from joymedia.api.storyboard import _plan_project, import_storyboard_workbook
	from joymedia.services.intake.action_reference import ensure_action_analysis
	from joymedia.services.intake.cinematography import ensure_project_camera_analysis
	from joymedia.services.intake.project import coalesce_existing_named_views
	from joymedia.services.planning.creative import (
		draft_script,
		reference_inventory,
		script_exemplars,
		script_workbook,
		unique_scene_names,
	)

	batch = frappe.get_doc("Creative Batch", batch_name)
	if batch.status == "Cancelled":
		return
	if partner_batch_waits_for_gpu(batch.owner):
		return
	frappe.set_user(batch.owner)
	request = frappe.parse_json(batch.request_json)
	variants = frappe.parse_json(batch.variants_json)
	selected_index = _prepare_position(variants, position)
	for index, variant in enumerate(variants):
		if index != selected_index:
			continue
		if not _write(batch.name, variants, "Planning", changed_index=index):
			return
		try:
			project = (
				frappe.get_doc("Media Project", variant["project"])
				if variant.get("project")
				else _create_variant(batch, request, index, variant.get("hero_product"))
			)
			variant.update(project=project.name, status="Planning")
			if not _write(batch.name, variants, "Planning", changed_index=index):
				return
			coalesce_existing_named_views(project)
			ensure_project_camera_analysis(project)
			ensure_action_analysis(project)
			reference_inventory(project)
			frappe.db.commit()
			if not variant.get("script"):
				# The batch brief is authoritative even when resuming an older
				# variant whose project description predates a revised request.
				project.video_idea = request.get("direction") or project.video_idea
				prior_script_errors = [
					{"scope": "Current", "category": "Rejected screenplay", "text": row["error"][-1800:]}
					for row in (variant.get("script_attempts") or [])[
						int(variant.get("script_context_start") or 0) :
					][-2:]
					if row.get("error")
				]
				script = draft_script(
					project,
					nonce=variant["nonce"],
					review_notes=[*(request.get("review_notes") or []), *prior_script_errors],
					previous=[v["script"]["logline"] for v in variants[:index] if v.get("script")],
					examples=script_exemplars(request.get("example_workbooks"), index),
					hero_product=variant.get("hero_product"),
					revision=variant.get("revision"),
					language=request.get("language"),
					require_clean=is_automatic(request) and not variant.get("accept_advisory_fallback"),
				)
				if is_automatic(request):
					defects = _automatic_script_defects(script)
					if defects:
						if _restart_automatic_script_variant(variant, script, defects):
							_write(batch.name, variants, "Planning", changed_index=index)
							_queue_prepare(batch.name, variants, replacement=True)
							frappe.db.commit()
							return
						# The script already passed every hard validator in ``draft_script``;
						# the remaining Director notes are advice, and they can contradict
						# each other. After the bounded rewrites an automatic video continues
						# with them kept for the production team instead of stopping.
						script["director_notes"] = list(
							dict.fromkeys([*(script.get("director_notes") or []), *defects])
						)
				if any(
					v.get("script", {}).get("logline", "").casefold() == script["logline"].casefold()
					for v in variants[:index]
				):
					raise ValueError("The proposed variant repeats an earlier concept.")
				variant["script"] = script
				_name_video(project, script)
				if not _write(batch.name, variants, "Planning", changed_index=index):
					return
			script = variant["script"]
			# Check saved scripts on resume as well as newly generated drafts.
			# Retries must not bypass a newly enforced physical consistency gate.
			blocking_defects = _blocking_script_defects(script)
			if blocking_defects:
				if _restart_automatic_script_variant(variant, script, blocking_defects):
					_write(batch.name, variants, "Planning", changed_index=index)
					_queue_prepare(batch.name, variants, replacement=True)
					frappe.db.commit()
					return
				raise ValueError(
					"AI Director could not produce a physically coherent action sequence after retries."
				)
			original_names = [scene.get("beat_name") for scene in script["scenes"]]
			unique_scene_names(script)
			if original_names != [scene["beat_name"] for scene in script["scenes"]]:
				# A previously saved AI script may already have imported duplicate
				# scene labels. Reimport its workbook before planning those shots.
				variant.pop("workbook", None)
				if not _write(batch.name, variants, "Planning", changed_index=index):
					return
			if not variant.get("workbook") and not variant.get("product_views_prepared"):
				from joymedia.services.planning.product_views import (
					apply_requested_view_sequence,
					prepare_script_product_views,
					requested_view_sequence,
				)

				# The finished Director script is the source of truth for product camera
				# requirements. Prepare any missing, explicitly-labelled AI candidates
				# before the storyboard binds product media to individual frames.
				apply_requested_view_sequence(script, request.get("direction") or project.video_idea)
				variant["product_views"] = prepare_script_product_views(project, script)
				from joymedia.services.planning.product_views import prepare_script_product_cutouts

				variant["product_cutouts"] = prepare_script_product_cutouts(project, script)
				variant["product_views_prepared"] = True
				# A client-requested angle cannot be fulfilled by silently binding
				# the original photograph under a different view label. Stop before
				# storyboard import so the project asks for a real additional view.
				requested_angles = set(requested_view_sequence(request.get("direction")))
				missing_angles = sorted(
					{
						row.get("view")
						for row in variant["product_views"]
						if row.get("view") in requested_angles and row.get("status") == "source_locked"
					}
				)
				if missing_angles:
					raise ValueError(
						"Requested product angle(s) could not be verified: "
						+ ", ".join(missing_angles)
						+ ". Supply a real photograph of each missing side before automatic rendering."
					)
				project.reload()
				if not _write(batch.name, variants, "Planning", changed_index=index):
					return
			if not variant.get("workbook") and not variant.get("pose_prepared"):
				from joymedia.services.planning.pose_assets import prepare_script_pose_views

				# The director has named every action. Prepare missing reusable
				# character poses now, before the text storyboard is imported and
				# before any scene first frame or H3 job is submitted.
				variant["pose_views"] = prepare_script_pose_views(project, script)
				variant["pose_prepared"] = True
				pose_defects = _pose_transition_defects(script, variant["pose_views"])
				if pose_defects:
					if _restart_automatic_script_variant(
						variant, script, pose_defects, extra_budget=AUTOMATIC_POSE_SCRIPT_REDRAWS
					):
						_write(batch.name, variants, "Planning", changed_index=index)
						_queue_prepare(batch.name, variants, replacement=True)
						frappe.db.commit()
						return
					raise ValueError(
						"Automatic script retained an unsupported body transition: " + pose_defects[0]
					)
				# A failed pose may trigger a bounded screenplay rewrite. Do not
				# submit a first frame from an incompatible source after that retry.
				_admit_pose_preparation(variant)
				project.reload()
				if not _write(batch.name, variants, "Planning", changed_index=index):
					return
			if not variant.get("workbook"):
				file = save_file(
					f"{batch.name}-variant-{index + 1}.xlsx",
					script_workbook(script, project),
					"Media Project",
					project.name,
					is_private=1,
				)
				with pinned_execution(project.name, request["generation_pipeline"]):
					import_storyboard_workbook(project.name, file.name, "Storyboard")
				project.reload()
				# The workbook is generated by the writer. Its camera_move cells are
				# proposals, not client-authored instructions; the shared shot policy
				# resolves them against action, framing and available endpoints.
				source = frappe.parse_json(project.storyboard_source_json or "{}") or {}
				source["generation_origin"] = "ai_director"
				project.db_set("storyboard_source_json", frappe.as_json(source))
				project.storyboard_source_json = frappe.as_json(source)
				project.soundtrack_prompt = script["music"]
				project.save(ignore_permissions=True)
				variant.update(workbook=file.file_url, title=script["title"])
				if not _write(batch.name, variants, "Planning", changed_index=index):
					return
			# Normal timed-sheet planning derives camera and physical contracts.
			plans = _plan_project(project, set(), apply=True)
			if any(p.get("held_back") for p in plans):
				raise ValueError("One or more scenes could not be planned faithfully.")
			variant["plans"] = [{"shot": p["shot"], "notes": p.get("notes", [])} for p in plans]
			if (
				index == 0
				and not request["auto_render"]
				and not _select_variant(batch, request, project.name)
			):
				return
			# Every storyboard comes with its scenes' first frames, not words only; the
			# video waits for the picture review either way.
			with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
				frappe.db.commit()
				if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
					return
				_start_keyframes(project, variant, request, batch.name)
				frappe.db.commit()
		except Exception as exc:
			frappe.db.rollback()
			if _defer_planner_outage(variant, exc):
				_write(batch.name, variants, "Planning", changed_index=index)
				frappe.db.commit()
				return
			if _defer_reference_analysis(variant, exc):
				_write(batch.name, variants, "Planning", changed_index=index)
				frappe.db.commit()
				return
			if _defer_lost_comfy_job(variant, exc):
				_write(batch.name, variants, "Planning", changed_index=index)
				frappe.db.commit()
				return
			if isinstance(exc, UnverifiedPoseRequirements) and _restart_script_after_pose_shortfall(variant):
				_write(batch.name, variants, "Planning", changed_index=index)
				_queue_prepare(batch.name, variants, replacement=True)
				frappe.db.commit()
				return
			# A rejected screenplay has not produced any media yet.  Retry it in
			# both delivery modes: assisted mode controls review after pictures are
			# made, not whether the Director may recover from a text-only failure.
			if _redraw_invalid_automatic_script(variant, exc):
				if variant["status"] == "Keyframes":
					# An earlier drawn concept is finished instead: rendering continues.
					_write(batch.name, variants, "Rendering", changed_index=index)
					frappe.db.commit()
					return
				_write(batch.name, variants, "Planning", changed_index=index)
				_queue_prepare(batch.name, variants, replacement=True)
				frappe.db.commit()
				return
			if _transient(exc):
				# A concurrent write conflict: the scheduler resumes this variant next minute.
				return
			variant.update(resume_stage=variant["status"], status="Needs Attention", error=str(exc)[:1600])
			frappe.log_error(title=f"Automatic creative variant failed: {batch.name}/{index + 1}")
		if not _write(batch.name, variants, changed_index=index):
			return
		# Yield the worker between variants so image/video submission is not starved.
		_queue_prepare(batch.name, variants)
		frappe.db.commit()
		return


def revise_variant(batch_name, position, notes):
	"""Rewrite a not-yet-rendered script from reviewer notes.

	Notes on named scenes at picture review rewrite those scenes in place; other
	notes produce a fresh version project. Earlier scripts stay as history and
	nothing already rendered changes.
	"""
	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		batch = frappe.get_doc("Creative Batch", batch_name)
		if batch.status == "Cancelled":
			raise ValueError("A stopped batch cannot be revised.")
		variants = frappe.parse_json(batch.variants_json)
		if position >= len(variants):
			raise ValueError("Choose an existing video.")
		variant = variants[position]
		if variant["status"] not in {"Script Ready", "Pictures Ready"} and not (
			variant["status"] == "Needs Attention"
			and variant.get("script")
			and not variant.get("generation_request")
		):
			raise ValueError("Only a script that has not been rendered yet can be rewritten.")
		variant.setdefault("history", []).append(
			{k: variant.get(k) for k in ("project", "workbook", "script", "title") if variant.get(k)}
		)
		in_place = variant["status"] == "Pictures Ready" and all(n.get("scene") for n in notes)
		if in_place:
			# Notes on named scenes at picture review: rewrite just those scenes in
			# this project and keep every other scene and its picture.
			variant["scene_revision"] = {"notes": notes, "by": frappe.session.user}
			variant["status"] = "Rewriting"
		else:
			variant["revision"] = {"script": variant["script"], "notes": notes, "by": frappe.session.user}
			for key in (
				"project",
				"workbook",
				"script",
				"title",
				"plans",
				"error",
				"resume_stage",
				"location_job",
				"keyframe_request",
				"picture_notes",
				"auto_redraws",
			):
				variant.pop(key, None)
			variant["status"] = "Queued"
	if in_place:
		_write(batch_name, variants, changed_index=position)
		frappe.enqueue(
			"joymedia.services.generation.creative_batch.rewrite_scenes_in_place",
			queue=_planning_queue(),
			timeout=3600,
			batch_name=batch_name,
			position=position,
			job_id=f"joymedia-creative-rewrite:{batch_name}:{position}",
			deduplicate=True,
			enqueue_after_commit=True,
		)
	else:
		_write(batch_name, variants, "Planning", changed_index=position)
		_queue_prepare(batch_name, variants)
	frappe.db.commit()
	return {"batch": batch_name, "index": position + 1, "status": variants[position]["status"]}


def _locked_variant(batch_name, position, *statuses):
	batch = frappe.get_doc("Creative Batch", batch_name)
	if batch.status == "Cancelled":
		raise ValueError("A stopped batch cannot continue.")
	variants = frappe.parse_json(batch.variants_json)
	if position >= len(variants) or variants[position]["status"] not in statuses:
		raise ValueError("This video is not waiting for that review.")
	return batch, variants, variants[position]


def approve_variant_pictures(batch_name, position):
	"""The reviewer accepts every scene picture: approve them and make the video."""
	from joymedia.services.keyframes.stage import set_keyframe_approval

	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		batch, variants, variant = _locked_variant(batch_name, position, "Pictures Ready")
		project = frappe.get_doc("Media Project", variant["project"])
		shots = frappe.get_all(
			"Shot",
			filters={"media_project": project.name, "is_removed": 0},
			fields=["name", "keyframe_artifact", "keyframe_status"],
		)
		if not shots or any(not s.keyframe_artifact and not _explicit_first_frame(s.name) for s in shots):
			raise ValueError("Redraw the scenes that have no picture before approving.")
		for shot in shots:
			if shot.keyframe_status != "Approved":
				set_keyframe_approval(project.name, shot.name)
		project.reload()
		request = frappe.parse_json(batch.request_json)
		with (
			pinned_execution(project.name, request["generation_pipeline"]),
			delivery_context(request, batch.name),
		):
			variant.update(status="Rendering", generation_request=project.generate_video(), picture_notes={})
		frappe.db.commit()
	_write(batch_name, variants, changed_index=position)
	return {"batch": batch_name, "index": position + 1, "status": "Rendering"}


def redraw_variant_picture(batch_name, position, shot_name):
	"""Draw one scene picture again; the video waits for the new picture."""
	from joymedia.services.keyframes.stage import generate_keyframes

	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		# Several pictures can be redrawn one after another; each scene guards its own job.
		batch, variants, variant = _locked_variant(batch_name, position, "Pictures Ready", "Keyframes")
		if frappe.db.get_value("Shot", shot_name, "media_project") != variant["project"]:
			raise ValueError("That scene belongs to another video.")
		request = frappe.parse_json(batch.request_json)
		with pinned_execution(variant["project"], request["generation_pipeline"]):
			variant.update(
				status="Keyframes",
				keyframe_request=generate_keyframes(variant["project"], [shot_name], draw_places=False),
			)
		frappe.db.commit()
	_write(batch_name, variants, changed_index=position)
	return {"batch": batch_name, "index": position + 1, "status": "Keyframes"}


def retry_variant_scene_with_prompt(batch_name, position, shot_name, instruction=""):
	"""Rewrite the H3 direction for one completed scene and render only that take.

	The first frame and its product references deliberately stay in place.  A
	per-shot prompt correction is normally about action, camera, pace or unwanted
	actors; retaining the approved opening frame is the safest way to preserve
	product artwork while the video model makes a new clip.  Unlike the older
	``regenerate_scene`` button, this also returns the batch to its automatic
	finishing path, so the replacement reaches the progressive and final films.
	"""
	from joymedia.services.generation.takes import _ensure_scene_free, regenerate_scene
	from joymedia.services.planning.signature import compute_plan_signature

	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		batch = frappe.get_doc("Creative Batch", batch_name)
		if batch.status == "Cancelled":
			raise ValueError("A stopped batch cannot create another scene.")
		variants = frappe.parse_json(batch.variants_json)
		if position < 0 or position >= len(variants):
			raise ValueError("That video variant does not exist.")
		variant = variants[position]
		if not variant.get("project"):
			raise ValueError("This video does not have a project yet.")
		project = frappe.get_doc("Media Project", variant["project"])
		shot = frappe.get_doc("Shot", shot_name)
		if shot.media_project != project.name or shot.is_removed:
			raise ValueError("That scene belongs to another video.")
		# Do not replace a prompt while its existing take is in the GPU queue.
		_ensure_scene_free(project, shot)

		instruction = str(instruction or "").strip()
		old_prompt = shot.generation_prompt or ""
		summary = "Rendered another take from the current approved direction."
		if instruction:
			from joymedia.services.planning.llm import generate_shot_revision

			revision = generate_shot_revision(
				instruction=instruction,
				shot=shot,
				product_name=project.product_name,
				video_idea=project.video_idea,
			)
			new_prompt = str(revision.get("generation_prompt") or "").strip()
			if not new_prompt:
				raise ValueError("The prompt editor did not return a usable video direction.")
			shot.generation_prompt = new_prompt
			# Keep image_prompt intact: this retry intentionally retains the existing
			# storyboard/keyframe and its source-art product binding.
			shot.save(ignore_permissions=True)
			summary = str(revision.get("summary") or "AI revised the scene direction.")[:500]
			# This is an explicit user-approved micro-edit.  Re-seal the immutable
			# plan signature so a full storyboard review is not made a blocker.
			project.reload()
			project.db_set(
				"approved_plan_signature", compute_plan_signature(project.name), update_modified=False
			)

		request = frappe.parse_json(batch.request_json)
		# A new take must be selected over the old one when it passes.  The old
		# asset remains in take history; clearing the draft selection makes the
		# automatic selector choose the new run rather than silently retain it.
		previous_take = shot.selected_output_asset_version
		frappe.db.set_value("Shot", shot.name, "selected_output_asset_version", None, update_modified=False)
		with (
			pinned_execution(project.name, request["generation_pipeline"]),
			delivery_context(request, batch.name),
		):
			generation_request = regenerate_scene(project.name, shot.name, automatic=True)
		variant.update(
			status="Rendering",
			generation_request=generation_request,
			error="",
			resume_stage=None,
		)
		variant.setdefault("scene_prompt_revisions", []).append(
			{
				"shot": shot.name,
				"instruction": instruction,
				"summary": summary,
				"previous_take": previous_take,
				"previous_prompt": old_prompt,
			}
		)
		frappe.db.commit()
	_write(batch_name, variants, changed_index=position)
	return {
		"batch": batch_name,
		"index": position + 1,
		"shot_name": shot.name,
		"status": "Rendering",
		"summary": summary,
	}


def held_scene_clips(project_name):
	"""Each scene still without a selected take, with the clip a person can review.

	A finished take the automatic check could not qualify is offered first
	(accepting it selects it); otherwise the latest held clip, which may be
	accepted only under the same rule as retaining held footage by hand.
	"""
	from joymedia.services.consistency.repair import held_take_review_candidate
	from joymedia.services.generation.takes import scene_takes
	from joymedia.services.review.admission import report_for

	clips = []
	for shot in frappe.get_all(
		"Shot",
		filters={
			"media_project": project_name,
			"is_removed": 0,
			"selected_output_asset_version": ["is", "not set"],
		},
		fields=["name", "shot_name", "shot_number"],
		order_by="shot_number asc",
	):
		clip = {"shot": shot.name, "shot_name": shot.shot_name, "shot_number": shot.shot_number}
		row = frappe.db.sql(
			"""select a.name, a.creation, f.frappe_file from `tabGeneration Attempt` a
			join `tabGeneration Task` t on a.generation_task = t.name
			join `tabGeneration Artifact` f on f.generation_attempt = a.name and f.artifact_role = 'Primary Video'
			where t.shot = %s and a.status = 'Failed' order by a.creation desc limit 1""",
			shot.name,
			as_dict=True,
		)
		take = _current_take(shot.name, scene_takes(project_name, shot.name))
		unlocked = (
			[
				"Product print not locked (the pack moved too much to track): compare its label with your product photo."
			]
			if frappe.db.exists("File", {"file_name": ["like", f"%-{shot.name}-product-unlocked%.json"]})
			else []
		)
		# Offer the newest footage: a take composed for an earlier direction, or
		# older than the latest held render, is not what the reviewer must judge.
		if take and not (row and row[0].creation > frappe.db.get_value("Asset Version", take, "creation")):
			version = take
			clip.update(
				asset_version=version,
				url=frappe.db.get_value("Asset Version", version, "file"),
				findings=unlocked,
				reviewable=True,
			)
			clips.append(clip)
			continue
		report = report_for(row[0].name) if row else None
		clip.update(
			attempt=row[0].name if row else None,
			url=row[0].frappe_file if row else None,
			findings=unlocked
			+ list(
				dict.fromkeys(
					r.get("reason") or r.get("claim")
					for r in (report or {}).get("results", [])
					if r.get("verdict") != "supported" and r.get("id") != "geometry_qualification"
				)
			)[:3],
			reviewable=bool(report and held_take_review_candidate(report)),
		)
		clips.append(clip)
	return clips


def _current_take(shot_name, takes):
	"""The newest take still made for the scene's current direction."""
	from joymedia.services.review.lineage import take_direction_changed

	shot = frappe.get_doc("Shot", shot_name)
	for take in reversed(takes):
		shot.selected_output_asset_version = take.name  # evaluated in memory only
		if not take_direction_changed(shot):
			return take.name
	return None


def accept_held_clip(batch_name, position, shot_name, note, attempt_name=None, asset_version=None):
	"""A reviewer watched a scene's clip and accepts it as the scene's take."""
	from pathlib import Path

	from joymedia.services.generation.takes import retain_held_take_for_review, use_reviewed_take
	from joymedia.services.review.admission import digest

	batch = frappe.get_doc("Creative Batch", batch_name)
	variants = frappe.parse_json(batch.variants_json)
	variant = variants[position]
	if batch.status == "Cancelled" or variant["status"] != "Needs Attention" or not variant.get("project"):
		raise ValueError("Only a stopped video's held scenes can be reviewed.")
	if frappe.db.get_value("Shot", shot_name, "media_project") != variant["project"]:
		raise ValueError("That scene belongs to another video.")
	current = frappe.db.get_value("Shot", shot_name, "selected_output_asset_version")
	if not asset_version:
		artifact = frappe.get_doc(
			"Generation Artifact", {"generation_attempt": attempt_name, "artifact_role": "Primary Video"}
		)
		source = digest(
			Path(frappe.get_doc("File", {"file_url": artifact.frappe_file}).get_full_path()).read_bytes()
		)
		asset_version = retain_held_take_for_review(
			variant["project"], shot_name, attempt_name, current, source, note
		)["asset_version"]
	use_reviewed_take(variant["project"], shot_name, asset_version, current)
	variant.setdefault("reviewed_clips", []).append(
		{"shot": shot_name, "asset_version": asset_version, "note": note, "by": frappe.session.user}
	)
	_write(batch_name, variants, changed_index=position)
	return {"shot": shot_name, "asset_version": asset_version}


def rerender_failed_scenes(variant, request):
	from joymedia.services.generation.takes import _start_takes_run

	project = frappe.get_doc("Media Project", variant["project"])
	# A transient batch-state failure can happen *after* the native run has
	# completed but before its takes were selected. Recover those finished takes
	# before deciding which scenes need another expensive GPU render.
	prior_run = (variant.get("generation_request") or {}).get("run")
	if (
		is_automatic(request)
		and prior_run
		and frappe.db.get_value("Generation Run", prior_run, "status") in {"Completed", "Failed"}
	):
		_select_automatic_outputs(project.name, prior_run, variant)
	failed = frappe.get_all(
		"Shot",
		filters={
			"media_project": project.name,
			"is_removed": 0,
			"selected_output_asset_version": ["is", "not set"],
		},
		pluck="name",
	)
	if not failed:
		return
	blocked = _nonretryable_scene_failure(prior_run, failed)
	if blocked:
		raise ValueError(
			f"Scene {blocked['shot']} needs revised inputs or workflow before rerendering: {blocked['reason']}"
		)
	with pinned_execution(project.name, request["generation_pipeline"]), delivery_context(request):
		variant["generation_request"] = _start_takes_run(project, failed, retry_reason="Manual Retry")


def rewrite_scenes_in_place(batch_name, position):
	"""Background job: rewrite only the noted scenes, re-plan and redraw only them."""
	import uuid

	from frappe.utils.file_manager import save_file

	from joymedia.api.storyboard import _plan_project, approve_project_storyboard
	from joymedia.services.keyframes.stage import generate_keyframes
	from joymedia.services.planning.creative import draft_script, script_exemplars, script_workbook
	from joymedia.services.planning.plan_parsing import _rescale_motion_plan
	from joymedia.services.planning.timed_actions import read_timed_actions
	from joymedia.services.planning.workbook import parse_storyboard_workbook

	batch = frappe.get_doc("Creative Batch", batch_name)
	frappe.set_user(batch.owner)
	request = frappe.parse_json(batch.request_json)
	variants = frappe.parse_json(batch.variants_json)
	variant = variants[position]
	if batch.status == "Cancelled" or variant["status"] != "Rewriting":
		return
	try:
		project = frappe.get_doc("Media Project", variant["project"])
		old = variant["script"]
		pose_scenes = variant["scene_revision"].get("pose_scenes")
		if pose_scenes:
			# A retry after a pose stop: the script stands. Only those scenes' opening
			# poses are resolved again, rebound and redrawn below.
			script = copy.deepcopy(old)
			changed = sorted(n - 1 for n in pose_scenes if 0 < n <= len(old["scenes"]))
		else:
			notes = variant["scene_revision"]["notes"]
			script = draft_script(
				project,
				nonce=uuid.uuid4().hex,
				examples=script_exemplars(request.get("example_workbooks"), position),
				hero_product=variant.get("hero_product"),
				revision={"script": old, "notes": notes},
				language=request.get("language"),
			)
			changed = sorted({n["scene"] - 1 for n in notes if 0 < n["scene"] <= len(old["scenes"])})
			for i in range(len(script["scenes"])):
				if i not in changed:
					script["scenes"][i] = old["scenes"][i]
					continue
				# Same beat name and duration: the shot, its timeline slot and the film length stay.
				scene, duration = script["scenes"][i], old["scenes"][i]["duration_seconds"]
				phases = read_timed_actions(scene["action"])
				plan = {"duration_seconds": duration, "motion_plan": {"actions": phases}}
				_rescale_motion_plan(plan, phases[-1]["end"])
				scene.update(beat_name=old["scenes"][i]["beat_name"], duration_seconds=duration)
				scene["action"] = "\n".join(
					f"[{row['start']:.9f}-{row['end']:.9f}s] {row['action']}"
					for row in plan["motion_plan"]["actions"]
				)
			script["duration_seconds"] = old["duration_seconds"]
			from joymedia.services.planning.creative import vary_against_neighbours

			# The camera director ran before the untouched scenes were restored: vary
			# each rewritten scene against its real neighbours (whose pictures stay).
			script.setdefault("camera_adjustments", []).extend(
				change for i in changed for change in vary_against_neighbours(script["scenes"], i)
			)
		# A scene rewrite can change the opening body state. Resolve its cast views
		# again before importing the workbook; the old shot may still point at a
		# pose whose qualification has since been revoked.
		if changed and any(script["scenes"][i].get("cast") for i in changed):
			from joymedia.services.planning.pose_assets import prepare_script_pose_views

			variant["pose_views"] = prepare_script_pose_views(project, script)
			_admit_revised_pose_preparation(variant, script)
			project.reload()
		content = script_workbook(script, project)
		file = save_file(
			f"{batch.name}-variant-{position + 1}-r{len(variant.get('history', []))}.xlsx",
			content,
			"Media Project",
			project.name,
			is_private=1,
		)
		parsed = parse_storyboard_workbook(file.get_full_path())["demos"][0]["scenes"]
		source = frappe.parse_json(project.storyboard_source_json)
		for i in changed:
			source["selected_demo"]["scenes"][i] = parsed[i]
		project.db_set("storyboard_source_json", frappe.as_json(source))
		shots = frappe.get_all(
			"Shot",
			filters={"media_project": project.name, "is_removed": 0},
			pluck="name",
			order_by="shot_number asc",
		)
		wanted = {shots[i] for i in changed}
		project.reload()
		_plan_project(project, wanted, apply=True)
		approve_project_storyboard(project.name)
		with pinned_execution(project.name, request["generation_pipeline"]):
			request_run = generate_keyframes(project.name, sorted(wanted))
		variant.update(
			script=script,
			workbook=file.file_url,
			status="Keyframes",
			keyframe_request=request_run,
			scene_revision=None,
			error="",
		)
		variant["auto_redraws"] = [s for s in variant.get("auto_redraws", []) if s not in wanted]
	except Exception as exc:
		frappe.db.rollback()
		if _transient(exc):
			return
		frappe.log_error(title=f"Scene rewrite failed: {batch_name}/{position + 1}")
		if isinstance(exc, UnverifiedPoseRequirements) or (variant.get("scene_revision") or {}).get(
			"pose_scenes"
		):
			# A pose retry that did not finish leaves those shots on their old
			# character view; never continue to first frames from them.
			variant.update(
				resume_stage="Keyframes",
				status="Needs Attention",
				error=str(exc)[:1600],
				scene_revision=None,
			)
		elif is_automatic(request) or request.get("auto_first_frames"):
			# A rewrite that cannot be written is a spent repair, not a reason to stop
			# the video: return to the existing pictures and let the repair ladder go on
			# (another rewrite, a new concept, or delivery with the scene flagged).
			variant.setdefault("repair_failures", []).append(str(exc)[:600])
			variant.update(status="Keyframes", scene_revision=None, error="")
		else:
			variant.update(
				resume_stage="Keyframes",
				status="Needs Attention",
				error="Scene rewrite failed: " + str(exc)[:1580],
			)
	_write(batch_name, variants, changed_index=position)


def start_variant_render(batch_name, position):
	"""Continue a reviewed "Script Ready" variant through the native visual stages."""
	with frappe.cache.lock(f"joymedia-creative:{batch_name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		batch = frappe.get_doc("Creative Batch", batch_name)
		if batch.status == "Cancelled":
			raise ValueError("A stopped batch cannot render.")
		variants = frappe.parse_json(batch.variants_json)
		if position >= len(variants) or variants[position]["status"] != "Script Ready":
			raise ValueError("Only a written, not yet rendered script can be approved for video.")
		variant = variants[position]
		project = frappe.get_doc("Media Project", variant["project"])
		_start_keyframes(project, variant, frappe.parse_json(batch.request_json), batch.name)
		frappe.db.commit()
	_write(batch_name, variants, changed_index=position)
	return {"batch": batch_name, "index": position + 1, "status": variant["status"]}


def _select_variant(batch, request, project_name):
	"""Navigate only to a ready script/export, preserving a newer user choice."""
	from joymedia.services.project.versions import set_working_edit

	root = request["root_project"]
	with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
		frappe.db.commit()
		if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
			return False
		frappe.db.sql("select name from `tabMedia Project` where name=%s for update", root)
		if (frappe.db.get_value("Media Project", root, "current_edit") or root) == request[
			"expected_current"
		]:
			set_working_edit(root, project_name, request["expected_current"])
		frappe.db.commit()
		return True


def _start_keyframes(project, variant, request=None, batch_name=None):
	from joymedia.api.storyboard import approve_project_storyboard
	from joymedia.services.keyframes.locations import assign_places, missing_places, missing_views

	# The batch owns the handoff after background preparation. A cancelled batch
	# cannot later submit frames/video from an orphaned location callback.
	approve_project_storyboard(project.name)
	project.reload()
	shots = [
		frappe.get_doc("Shot", name)
		for name in frappe.get_all(
			"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name"
		)
	]
	assign_places(project, shots)
	if missing_places(project, shots) or missing_views(project, shots):
		job_id = f"joymedia-creative-locations:{project.name}"
		frappe.enqueue(
			"joymedia.services.keyframes.locations.draw_project_places",
			queue="long",
			timeout=3600,
			project_name=project.name,
			shot_names=[s.name for s in shots],
			user=frappe.session.user,
			job_id=job_id,
			deduplicate=True,
			enqueue_after_commit=True,
		)
		variant.update(status="Locations", location_job=job_id)
		return
	_submit_visual_stage(project, variant, request, batch_name)


def _submit_visual_stage(project, variant, request=None, batch_name=None):
	from joymedia.services.keyframes.stage import generate_keyframes
	from joymedia.services.workflows.capabilities import controls

	with (
		pinned_execution(project.name, project.generation_pipeline),
		delivery_context(request or {}, batch_name),
	):
		if "reference_only" in controls(frappe.get_doc("Generation Workflow", project.workflow)):
			variant.update(status="Rendering", generation_request=project.generate_video())
		else:
			variant.update(
				status="Keyframes", keyframe_request=generate_keyframes(project.name, draw_places=False)
			)


def advance_batches():
	"""Scheduler resumes automation through native jobs, without blocking workers."""
	for batch_name in frappe.get_all(
		"Creative Batch",
		filters={"status": ["in", ["Queued", "Planning", "Rendering", "Finishing"]]},
		pluck="name",
	):
		batch = frappe.get_doc("Creative Batch", batch_name)
		if partner_batch_waits_for_gpu(batch.owner):
			continue
		variants = frappe.parse_json(batch.variants_json)
		_queue_prepare(batch.name, variants)
		if not any(
			v["status"] in {"Locations", "Keyframes", "Rendering", "Finishing", "Exporting"} for v in variants
		):
			continue
		if not is_render_alive(f"joymedia-creative-advance:{batch.name}"):
			frappe.enqueue(
				"joymedia.services.generation.creative_batch.advance_batch",
				queue="long",
				timeout=1800,
				batch_name=batch.name,
				user=batch.owner,
				job_id=f"joymedia-creative-advance:{batch.name}",
				deduplicate=True,
				enqueue_after_commit=True,
			)


def _unprotected(shot):
	"""Whether the picture's product label could not be locked to the original photo."""
	lock = (
		frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "product_lock_json")
		if shot.get("keyframe_artifact")
		else None
	)
	return bool(lock and (frappe.parse_json(lock) or {}).get("unprotected"))


def _explicit_first_frame(shot_name):
	return frappe.db.get_value(
		"Shot Reference", {"parent": shot_name, "reference_role": "first_frame"}, "asset_version"
	)


def _use_product_source_for_packshot(shot, without_frame=False):
	"""Use original artwork when a product-only generated frame fails visual review.

	A catalogue packshot does not need a synthetic actor or pose. Keeping its
	original image as the opening frame also avoids redrawing printed claims.
	``without_frame`` covers a packshot the product lock never let through.
	"""
	if (shot.consistency_status != "Needs Review" and not without_frame) or _explicit_first_frame(shot.name):
		return False
	from joymedia.services.scene.contract import read_contract

	contract = read_contract(shot.motion_plan_json) or {}
	entities = contract.get("entities") or []
	if (
		not entities
		or not any("product" in (entity.get("label") or "").lower() for entity in entities)
		or any(
			not any(word in (entity.get("label") or "").lower() for word in ("product", "setting"))
			for entity in entities
		)
	):
		return False
	refs = frappe.get_all(
		"Shot Reference", filters={"parent": shot.name}, fields=["reference_role", "asset_version"]
	)
	products = [r.asset_version for r in refs if frappe.scrub(r.reference_role or "") == "product"]
	if len(products) != 1 or any(frappe.scrub(r.reference_role or "") == "character" for r in refs):
		return False
	shot_doc = frappe.get_doc("Shot", shot.name)
	shot_doc.append("generation_inputs", {"reference_role": "first_frame", "asset_version": products[0]})
	shot_doc.save(ignore_permissions=True)
	return True


def _keyframe_ready(shot):
	if _explicit_first_frame(shot.name):
		from joymedia.services.keyframes.product_review import assert_product_frame_ready, has_product

		full_shot = shot if shot.get("generation_inputs") is not None else frappe.get_doc("Shot", shot.name)
		if has_product(full_shot):
			try:
				assert_product_frame_ready(
					frappe.get_doc("Media Project", full_shot.media_project), full_shot
				)
			except ValueError:
				return False
		return True
	if shot.consistency_status == "Passed" and not _unprotected(shot):
		return True
	if shot.get("keyframe_status") != "Approved":
		return False
	from joymedia.services.keyframes.stage import approved_keyframe_task

	# Honor an explicit native frame approval only while its artifact/signature
	# still matches. Preserve machine findings; approval is permission to animate,
	# not a fabricated physics pass or release approval.
	return bool(approved_keyframe_task(frappe.get_doc("Shot", shot.name)))


def _selected_review_outputs(project_name):
	"""Resume finishing after native take review/repair, without rewriting failed jobs."""
	from joymedia.services.generation.takes import scene_takes
	from joymedia.services.review.lineage import take_direction_changed

	if frappe.db.exists(
		"Generation Run", {"media_project": project_name, "status": ["in", ["Draft", "Queued", "Running"]]}
	):
		return False
	shots = frappe.get_all("Shot", filters={"media_project": project_name, "is_removed": 0}, pluck="name")
	if not shots:
		return False
	for name in shots:
		shot = frappe.get_doc("Shot", name)
		selected = shot.selected_output_asset_version
		if not selected or selected not in {row.name for row in scene_takes(project_name, name)}:
			return False
		version = frappe.get_doc("Asset Version", selected)
		evidence = frappe.parse_json(version.get("preservation_evidence_json") or "{}") or {}
		if (
			version.source == "Composed"
			and evidence.get("method") == "ffmpeg_zoompan_source_art"
			and version.derived_from == evidence.get("source_asset_version")
			and version.derived_from in {r.asset_version for r in shot.generation_inputs or []}
		):
			continue
		attempt = frappe.db.get_value("Asset Version", selected, "source_generation_attempt")
		task = frappe.db.get_value("Generation Attempt", attempt, "generation_task") if attempt else None
		if (
			not task
			or frappe.db.get_value("Generation Task", task, "shot") != name
			or take_direction_changed(shot)
		):
			return False
	return True


def _compose_product_insert_fallbacks(project_name, variant, batch_name, variant_index):
	"""Keep original artwork moving when H3 cannot protect a stationary packshot."""
	from joymedia.services.editing.rough_preview import queue_progressive_preview
	from joymedia.services.editing.source_motion import compose_source_motion_take
	from joymedia.services.generation.takes import scene_takes, select_scene_take
	from joymedia.services.planning.shot_structure import structure_for
	from joymedia.services.scene.contract import read_contract

	created = 0
	for name in frappe.get_all(
		"Shot",
		filters={
			"media_project": project_name,
			"is_removed": 0,
			"selected_output_asset_version": ["is", "not set"],
		},
		pluck="name",
	):
		shot = frappe.get_doc("Shot", name)
		structure = structure_for(shot)
		contract = read_contract(shot.motion_plan_json) or {}
		entities = contract.get("entities") or []
		if (
			not structure
			or structure["subject_motion"] != "stationary"
			or structure["stage"] not in {"establish", "detail", "inspect", "present", "hero"}
			or not entities
			or not any("product" in (e.get("label") or "").lower() for e in entities)
			or any(
				not any(word in (e.get("label") or "").lower() for word in ("product", "setting"))
				for e in entities
			)
		):
			continue
		refs = shot.generation_inputs or []
		products = [r.asset_version for r in refs if frappe.scrub(r.reference_role or "") == "product"]
		first = [r.asset_version for r in refs if frappe.scrub(r.reference_role or "") == "first_frame"]
		if len(products) != 1 or first != products:
			continue
		result = compose_source_motion_take(project_name, name, products[0], None)
		takes = scene_takes(project_name, name)
		position = next(i for i, take in enumerate(takes, 1) if take.name == result["asset_version"])
		previous = frappe.flags.get("joymedia_defer_finishing")
		frappe.flags.joymedia_defer_finishing = True
		try:
			select_scene_take(project_name, name, position)
		finally:
			frappe.flags.joymedia_defer_finishing = previous
		variant.setdefault("source_motion_fallbacks", {})[name] = result["asset_version"]
		created += 1
	if created:
		queue_progressive_preview(batch_name, variant_index, project_name)
	return created


def _select_automatic_outputs(project_name, run_name, variant):
	"""Select rendered takes for a complete, explicitly provisional film preview.

	A source-art warning stays a warning. No admission report or brand approval is
	changed, and older footage is never substituted for a failed current render.
	"""
	from joymedia.services.generation.takes import scene_takes, select_scene_take
	from joymedia.services.review.consistency import REDO, queue_check

	# The batch request authorizes automatic delivery. Consistency-triggered
	# replacement runs are native takes and may lack the request-scoped snapshot
	# flag; retain the original run as the provenance anchor for this batch.
	if not variant.get("automatic_origin_run"):
		snapshot = frappe.parse_json(
			frappe.db.get_value("Generation Run", run_name, "project_snapshot_json") or "{}"
		)
		if not snapshot.get("automatic_delivery"):
			return False
		variant["automatic_origin_run"] = run_name
	previous = frappe.flags.get("joymedia_defer_finishing")
	frappe.flags.joymedia_defer_finishing = True
	try:
		# A consistency check can schedule a replacement after the original run
		# completes. Follow that run before touching scene selections: the native
		# take selector correctly rejects edits while any project run is active.
		active = frappe.get_all(
			"Generation Run",
			filters={"media_project": project_name, "status": ["in", ["Draft", "Queued", "Running"]]},
			fields=["name"],
			order_by="modified desc",
			limit_page_length=1,
		)
		if active:
			variant["generation_request"] = {"run": active[0].name}
			return False
		ready = True
		for row in frappe.get_all(
			"Shot",
			filters={"media_project": project_name, "is_removed": 0},
			fields=["name", "selected_output_asset_version"],
			order_by="shot_number",
		):
			if row.selected_output_asset_version:
				status = frappe.db.get_value("Shot", row.name, "consistency_status")
				if status == "Needs Review":
					variant.setdefault("preview_findings", {})[row.name] = (
						frappe.db.get_value("Shot", row.name, "consistency_notes") or "visual review needed"
					)
					continue
				if status == REDO:
					# A complete draft comes before editorial retries. The machine
					# finding remains visible, while this usable take stays selected.
					variant.setdefault("preview_findings", {})[row.name] = (
						frappe.db.get_value("Shot", row.name, "consistency_notes") or "visual review needed"
					)
				if status == "Checking":
					ready = False
				continue
			takes = scene_takes(project_name, row.name)
			current = _current_take(row.name, takes)
			attempt = (
				frappe.db.get_value("Asset Version", current, "source_generation_attempt")
				if current
				else None
			)
			task = frappe.db.get_value("Generation Attempt", attempt, "generation_task") if attempt else None
			source_run = frappe.db.get_value("Generation Task", task, "generation_run") if task else None
			origin = variant.get("automatic_origin_run")
			# A later automatic replacement can fail while a preceding replacement
			# yielded a usable take. Keep that take in the draft, with its findings,
			# instead of returning to an earlier project version or blocking the film.
			if source_run != run_name and origin:
				origin_row = frappe.db.get_value(
					"Generation Run", origin, ["media_project", "creation"], as_dict=True
				)
				source_row = (
					frappe.db.get_value(
						"Generation Run", source_run, ["media_project", "creation"], as_dict=True
					)
					if source_run
					else None
				)
				if not (
					origin_row
					and source_row
					and origin_row.media_project == source_row.media_project == project_name
					and source_row.creation >= origin_row.creation
				):
					ready = False
					continue
			elif source_run != run_name:
				ready = False
				continue
			select_scene_take(
				project_name, row.name, next(i for i, take in enumerate(takes, 1) if take.name == current)
			)
			variant.setdefault("automatic_selections", []).append(
				{"shot": row.name, "asset_version": current, "quality_review": "checking"}
			)
			queue_check(row.name, "take")
			ready = False
		return ready
	finally:
		frappe.flags.joymedia_defer_finishing = previous


def _select_incremental_automatic_outputs(project_name, run_name, variant, batch_name, variant_index):
	"""Make completed automatic scenes visible before the complete run finishes.

	The selected take remains provisional and receives the normal consistency
	check.  Selection only changes the draft view; final finishing still waits for
	every scene.  A separate silent rough cut lets the customer see the film's
	pacing while later shots, voiceover and music are still being made.
	"""
	from joymedia.services.generation.takes import scene_takes
	from joymedia.services.review.consistency import queue_check

	snapshot = frappe.parse_json(
		frappe.db.get_value("Generation Run", run_name, "project_snapshot_json") or "{}"
	)
	if not snapshot.get("automatic_delivery") and not variant.get("automatic_origin_run"):
		return 0
	previous = frappe.flags.get("joymedia_defer_finishing")
	frappe.flags.joymedia_defer_finishing = True
	selected = 0
	try:
		for shot in frappe.get_all(
			"Shot",
			filters={
				"media_project": project_name,
				"is_removed": 0,
				"selected_output_asset_version": ["is", "not set"],
			},
			fields=["name"],
			order_by="shot_number asc",
		):
			takes = scene_takes(project_name, shot.name)
			current = _current_take(shot.name, takes)
			if not current:
				continue
			attempt = frappe.db.get_value("Asset Version", current, "source_generation_attempt")
			task = frappe.db.get_value("Generation Attempt", attempt, "generation_task") if attempt else None
			if not task or frappe.db.get_value("Generation Task", task, "generation_run") != run_name:
				continue
			# A run reserves all its scenes until it finishes, so the public take
			# selector correctly refuses edits here. This internal preview path may
			# select only a completed task with no other live task for this scene.
			if frappe.db.get_value("Generation Task", task, "status") != "Completed":
				continue
			if frappe.db.exists(
				"Generation Task",
				{
					"shot": shot.name,
					"status": ["not in", ["Completed", "Failed", "Cancelled"]],
				},
			):
				continue
			frappe.db.set_value(
				"Shot", shot.name, "selected_output_asset_version", current, update_modified=False
			)
			variant.setdefault("automatic_selections", []).append(
				{"shot": shot.name, "asset_version": current, "quality_review": "checking"}
			)
			queue_check(shot.name, "take")
			selected += 1
	finally:
		frappe.flags.joymedia_defer_finishing = previous
	if selected:
		from joymedia.services.editing.rough_preview import queue_progressive_preview

		queue_progressive_preview(batch_name, variant_index, project_name)
	return selected


def advance_batch(batch_name, user=None):
	from joymedia.services.audio.plan import build_audio_plan
	from joymedia.services.editing.export_jobs import queue_project_timeline_export
	from joymedia.services.editing.post_production import queue_post_production_internal
	from joymedia.services.keyframes.stage import set_keyframe_approval

	batch = frappe.get_doc("Creative Batch", batch_name)
	if batch.status == "Cancelled":
		return
	if partner_batch_waits_for_gpu(batch.owner):
		return
	frappe.set_user(batch.owner)
	variants = frappe.parse_json(batch.variants_json)
	request = frappe.parse_json(batch.request_json)
	automatic = is_automatic(request)
	automatic_pictures = automatic or bool(request.get("auto_first_frames"))
	for index, variant in enumerate(variants):
		if variant["status"] not in {"Locations", "Keyframes", "Rendering", "Finishing", "Exporting"}:
			continue
		project = frappe.get_doc("Media Project", variant["project"])
		try:
			if automatic and variant["status"] in {"Keyframes", "Rendering"}:
				stage_request = (
					variant.get(
						"keyframe_request" if variant["status"] == "Keyframes" else "generation_request"
					)
					or {}
				)
				if stage_request.get("run"):
					advance_automatic_run(stage_request["run"])
			if variant["status"] == "Locations":
				from joymedia.services.keyframes.locations import assign_places, missing_places, missing_views

				if is_render_alive(variant["location_job"]):
					continue
				shots = [
					frappe.get_doc("Shot", name)
					for name in frappe.get_all(
						"Shot", filters={"media_project": project.name, "is_removed": 0}, pluck="name"
					)
				]
				if missing_places(project, shots) or missing_views(project, shots):
					raise ValueError(
						"Shared-setting preparation did not complete. Inspect the native location job before retrying."
					)
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					assign_places(project, shots)
					project.reload()
					_submit_visual_stage(project, variant, request, batch.name)
					frappe.db.commit()
			elif variant["status"] == "Keyframes":
				active = frappe.db.exists(
					"Generation Run",
					{"media_project": project.name, "status": ["in", ["Draft", "Queued", "Running"]]},
				)
				if active:
					continue
				shots = frappe.get_all(
					"Shot",
					filters={"media_project": project.name, "is_removed": 0},
					fields=[
						"name",
						"shot_number",
						"keyframe_artifact",
						"keyframe_status",
						"consistency_status",
						"consistency_notes",
						"motion_plan_json",
					],
				)
				if not shots:
					raise ValueError("A keyframe job failed or did not produce an image.")
				originals = variant.get("frame_repair_original_artifacts") or {}
				if originals:
					unchanged = [
						s.name
						for s in shots
						if s.name in originals and s.keyframe_artifact == originals[s.name]
					]
					if unchanged:
						run_name = (variant.get("keyframe_request") or {}).get("run")
						if frappe.db.get_value("Generation Run", run_name, "status") in {
							"Failed",
							"Completed",
							"Cancelled",
						}:
							raise ValueError(
								"Repaired opening frame failed for "
								+ ", ".join(unchanged)
								+ "; the previous invalid frame was not reused."
							)
						continue
				redrawing = []
				for shot in shots:
					if shot.consistency_status != "Redrawing":
						continue
					if _redraws_exhausted(shot.name):
						shot.consistency_status = "Needs Review"
					else:
						redrawing.append(shot.name)
				if automatic_pictures and redrawing:
					# The consistency worker has supplied an evidence-backed retry
					# direction in the shot prompt.  A completed first-frame run used
					# to leave these scenes permanently in Redrawing because the batch
					# only waited for the status instead of submitting that next run.
					# ``generate_keyframes(..., automatic=True)`` preserves the review
					# service's bounded retry counter.
					from joymedia.services.keyframes.stage import generate_keyframes

					with frappe.cache.lock(
						f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10
					):
						frappe.db.commit()
						if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
							return
						_seal_automatic_plan(project.name)
						with (
							pinned_execution(project.name, project.generation_pipeline),
							delivery_context(request, batch.name),
						):
							variant["keyframe_request"] = generate_keyframes(
								project.name, redrawing, draw_places=False, automatic=True
							)
						frappe.db.commit()
					_write(batch.name, variants, changed_index=index)
					continue
				if any(s.consistency_status in {"Checking", "Redrawing"} for s in shots):
					continue
				if automatic_pictures:
					from joymedia.services.review.physical_audit import audit_frames

					audit_frames(project, shots, variant.setdefault("physical_audit", {}))
					_audit_rejected_first_frames(
						project,
						shots,
						(variant.get("keyframe_request") or {}).get("run"),
						variant.setdefault("rejected_frame_audit", {}),
					)
					# Cheapest fix first: redraw a frame the picture model got wrong, then
					# restage a scene, and only then write a whole new concept.
					if _start_frame_corrections(batch, variants, index, project, _frame_corrections(shots)):
						continue
					if _start_automatic_scene_repair(batch.name, variants, index, _scene_repair_notes(shots)):
						return
					critical = _critical_frame_defects(shots)
					if critical and _restart_automatic_script_variant(variant, variant["script"], critical):
						_write(batch.name, variants, "Planning", changed_index=index)
						_queue_prepare(batch.name, variants, replacement=True)
						frappe.db.commit()
						return
					for shot in shots:
						if _use_product_source_for_packshot(shot):
							variant.setdefault("source_frame_fallbacks", {})[shot.name] = (
								"Original product artwork replaced a rejected generated packshot."
							)
					# Keep visual concerns attached to the review export. A present
					# first frame can be used for automatic preview after bounded redraw;
					# only an absent artifact is a technical stop.
					variant["picture_notes"] = {
						s.name: s.consistency_notes
						for s in shots
						if s.consistency_status == "Needs Review" and s.consistency_notes
					}
				redrawn = variant.setdefault("auto_redraws", [])
				if automatic:
					# A packshot the product lock keeps rejecting opens on the original
					# product photo instead of stopping the whole video.
					for shot in shots:
						if (
							not shot.keyframe_artifact
							and _product_lock_rejected(
								(variant.get("keyframe_request") or {}).get("run"), shot.name
							)
							and _use_product_source_for_packshot(shot, without_frame=True)
						):
							variant.setdefault("source_frame_fallbacks", {})[shot.name] = (
								"Original product artwork replaced a packshot the product lock rejected."
							)
				missing = [
					s.name
					for s in shots
					if (not s.keyframe_artifact or _stale_keyframe(s.name))
					and not _explicit_first_frame(s.name)
					and redrawn.count(s.name) < AUTOMATIC_PICTURE_REDRAWS
				]
				if missing:
					blocked = _nonretryable_scene_failure(
						(variant.get("keyframe_request") or {}).get("run"), missing
					)
					if blocked:
						raise ValueError(
							f"Scene {blocked['shot']} needs revised inputs or workflow before another first-frame render: {blocked['reason']}"
						)
					# Picture generation is stochastic (about half of first drawings fail a
					# check): draw each failed picture again, through the same checks,
					# a bounded number of times before asking a person.
					from joymedia.services.keyframes.stage import generate_keyframes

					with frappe.cache.lock(
						f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10
					):
						frappe.db.commit()
						if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
							return
						if automatic_pictures:
							_correct_product_views(
								(variant.get("keyframe_request") or {}).get("run"), missing
							)
							_seal_automatic_plan(project.name)
						with (
							pinned_execution(project.name, project.generation_pipeline),
							delivery_context(request, batch.name),
						):
							variant["keyframe_request"] = generate_keyframes(
								project.name, missing, draw_places=False, automatic=True
							)
						redrawn.extend(missing)
						frappe.db.commit()
					_write(batch.name, variants, changed_index=index)
					continue
				if any(not s.keyframe_artifact and not _explicit_first_frame(s.name) for s in shots):
					raise ValueError(
						"First-frame generation exhausted its retries without producing an image."
					)
				if automatic:
					from joymedia.services.keyframes.product_review import (
						can_auto_approve_product_frame,
						has_product,
					)

					for selected_shot in shots:
						if not _explicit_first_frame(selected_shot.name):
							continue
						full_shot = frappe.get_doc("Shot", selected_shot.name)
						if (
							has_product(full_shot)
							and full_shot.keyframe_status != "Approved"
							and can_auto_approve_product_frame(project, full_shot)
						):
							set_keyframe_approval(project.name, full_shot.name)
					if any(_explicit_first_frame(s.name) and not _keyframe_ready(s) for s in shots):
						variant["status"] = "Needs Attention" if automatic_pictures else "Pictures Ready"
						if automatic_pictures:
							variant["resume_stage"] = "Keyframes"
							variant["error"] = (
								"Product opening did not pass the automatic first-frame checks."
							)
						_storyboard_with_frames(batch, variant, shots)
						variant["picture_notes"] = {
							s.name: "Product opening needs visual review before video."
							for s in shots
							if _explicit_first_frame(s.name) and not _keyframe_ready(s)
						}
						_write(batch.name, variants, changed_index=index)
						continue
				if any(not _keyframe_ready(s) for s in shots):
					# A bounded automatic repair that still has an unqualified first
					# frame must stop before animation in either delivery mode.
					variant["status"] = "Needs Attention" if automatic_pictures else "Pictures Ready"
					if automatic_pictures:
						variant["resume_stage"] = "Keyframes"
						variant["error"] = (
							"Automatic first-frame repair exhausted; scene inputs or the workflow need revision."
						)
					_storyboard_with_frames(batch, variant, shots)
					variant["picture_notes"] = {
						s.name: s.consistency_notes or ("" if s.keyframe_artifact else "No picture yet.")
						for s in shots
						if not s.keyframe_artifact or not _keyframe_ready(s)
					}
					_write(batch.name, variants, changed_index=index)
					continue
				_storyboard_with_frames(batch, variant, shots)
				if automatic:
					variant["frame_authorization"] = {
						"mode": "automatic",
						"quality_review": "deferred",
						"artifacts": {
							s.name: _explicit_first_frame(s.name) or s.keyframe_artifact for s in shots
						},
					}
				for shot in shots:
					if _explicit_first_frame(shot.name):
						continue  # the source control is already the selected video input
					with frappe.cache.lock(
						f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10
					):
						frappe.db.commit()
						if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
							return
						set_keyframe_approval(project.name, shot.name)
						frappe.db.commit()
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					project.reload()
					request = frappe.parse_json(batch.request_json)
					if automatic:
						_seal_automatic_plan(project.name)
					with (
						pinned_execution(project.name, request["generation_pipeline"]),
						delivery_context(request, batch.name),
					):
						repair_shots = variant.pop("frame_repair_shots", [])
						variant.pop("frame_repair_original_artifacts", None)
						if repair_shots:
							from joymedia.services.generation.takes import _start_takes_run

							generation_request = _start_takes_run(
								project, repair_shots, retry_reason="Manual Retry"
							)
						else:
							generation_request = project.generate_video()
						variant.update(status="Rendering", generation_request=generation_request)
					# The first complete, silent film is available as soon as all first
					# frames exist.  It gives the customer a real 30-second timeline
					# before any video job or soundtrack has completed.
					from joymedia.services.editing.rough_preview import queue_progressive_preview

					queue_progressive_preview(batch.name, index, project.name)
					frappe.db.commit()
			elif variant["status"] == "Rendering":
				run_name = variant.get("generation_request", {}).get("run")
				status = frappe.db.get_value("Generation Run", run_name, "status") if run_name else None
				if automatic and run_name and status in {"Queued", "Running"}:
					# Do not make a marketer wait for the last GPU job before they can
					# watch the pacing of the film.  This only produces a silent draft;
					# narration, music and the release export keep their full gates.
					if _select_incremental_automatic_outputs(
						project.name, run_name, variant, batch.name, index
					):
						_write(batch.name, variants, changed_index=index)
				if status in {"Draft", "Queued", "Running"}:
					continue
				if automatic and run_name and status in {"Completed", "Failed"}:
					selected_ready = _select_automatic_outputs(project.name, run_name, variant)
					if status == "Failed":
						if _compose_product_insert_fallbacks(project.name, variant, batch.name, index):
							selected_ready = _selected_review_outputs(project.name)
					if not selected_ready and variant.get("generation_request", {}).get("run") != run_name:
						# A native replacement is active; follow its own run.
						_write(batch.name, variants, changed_index=index)
						continue
					if not selected_ready and status == "Completed":
						_write(batch.name, variants, changed_index=index)
						continue
				if status != "Completed" and not (
					status == "Failed" and _selected_review_outputs(project.name)
				):
					if automatic and status == "Failed" and not variant.get("automatic_render_retry"):
						rerender_failed_scenes(variant, request)
						variant["automatic_render_retry"] = True
						_write(batch.name, variants, changed_index=index)
						continue
					raise ValueError(
						"Rendered scenes need attention. Inspect native generation evidence; quality gates remain in effect."
					)
				missing_outputs = frappe.get_all(
					"Shot",
					filters={
						"media_project": project.name,
						"is_removed": 0,
						"selected_output_asset_version": ["is", "not set"],
					},
					pluck="name",
				)
				if missing_outputs:
					raise ValueError(
						"Rendered scenes have no selected output yet: "
						+ ", ".join(missing_outputs)
						+ ". Output selection must finish before narration and editing."
					)
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					queue_post_production_internal(project.name)
					variant["status"] = "Finishing"
					variant.pop("error", None)
					frappe.db.commit()
			elif variant["status"] == "Finishing" and project.post_production_status == "Completed":
				# Post-production creates the video timeline.  Narration needs that
				# timeline to know the scene's exact start/end frames, so it must be
				# generated after this stage, never immediately after scene rendering.
				from joymedia.services.audio.speech import generate_voiceover

				for cue in build_audio_plan(project.name):
					if cue["role"] == "Voiceover" and not cue["scheduled"]:
						frappe.db.commit()
						if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
							return
						generate_voiceover(project.name, cue["shot"])
				with frappe.cache.lock(f"joymedia-creative:{batch.name}", timeout=180, blocking_timeout=10):
					frappe.db.commit()
					if frappe.db.get_value("Creative Batch", batch.name, "status") == "Cancelled":
						return
					queue_project_timeline_export(project.name, purpose="review")
					variant["status"] = "Exporting"
					frappe.db.commit()
			elif (
				variant["status"] == "Exporting"
				and project.export_status == "Completed"
				and project.current_output_asset_version
			):
				if index == 0 and not _select_variant(
					batch, frappe.parse_json(batch.request_json), project.name
				):
					return
				variant.update(
					status="Completed",
					output_asset_version=project.current_output_asset_version,
					video=frappe.db.get_value("Asset Version", project.current_output_asset_version, "file"),
				)
			elif project.post_production_status in {"Failed", "Cancelled"}:
				raise ValueError(project.post_production_error or "Finishing did not complete.")
			elif variant["status"] == "Exporting" and project.export_status == "Failed":
				attempts = int(variant.get("automatic_export_retries") or 0)
				if automatic and attempts < 2:
					frappe.db.commit()
					queue_project_timeline_export(project.name, purpose="review")
					variant["automatic_export_retries"] = attempts + 1
					variant.pop("error", None)
				else:
					raise ValueError(project.export_error or "Review export did not complete.")
		except Exception as exc:
			frappe.db.rollback()
			if _transient(exc):
				# A concurrent write conflict: the next scheduler tick retries this stage.
				continue
			variant.update(resume_stage=variant["status"], status="Needs Attention", error=str(exc)[:1600])
		_write(batch.name, variants, changed_index=index)
	# Completion or review may have freed a slot while this worker was running.
	_queue_prepare(batch.name, variants)
