"""Sampled visual review through the configured vision capability.

Cast count and broad action checks support bounded legacy retries. Explicit scene
contracts add independent ownership, source and event-order questions. Contract
failures and uncertainty request review rather than triggering uncalibrated GPU
retries. Missing media or an unavailable judge is Not Checked, never Passed.

A sampled pass cannot certify all frames, fine identity, packaging, or physics.
Source artwork preservation and exact-take release approval remain independent.
"""

import base64
import io
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

import frappe
import requests

from joymedia.services.project.realtime import PROJECT_UPDATED, publish_project_event
from joymedia.services.runtime.endpoints import endpoint, is_configured, structured_response
from joymedia.services.runtime.sampling import sampling
from joymedia.services.scene.evidence import SequenceCheck

MAX_FRAME_REDOS = 2
MAX_TAKE_REDOS = 1
TAKE_SAMPLES = 4
IMAGE_EDGE = 448  # bounded request size keeps vision checks repeatable across providers


def _automatic_preview_in_progress(project_name):
	"""A batch-owned preview keeps qualified takes available for whole-film review."""
	from joymedia.services.generation.automation import is_automatic

	try:
		batches = frappe.get_all(
			"Creative Batch",
			filters={"status": ["in", ["Queued", "Planning", "Rendering", "Finishing", "Needs Attention"]]},
			fields=["request_json", "variants_json"],
		)
	except Exception:
		# Visual review also runs during migrations and isolated repairs, where
		# the optional batch doctype may not be available.  Such a scene is not
		# owned by an automatic preview.
		return False
	for batch in batches:
		if not is_automatic(frappe.parse_json(batch.request_json or "{}")):
			continue
		if any(
			variant.get("project") == project_name
			for variant in frappe.parse_json(batch.variants_json or "[]")
		):
			return True
	return False


def queue_check(shot_name, kind):
	"""Check the scene's new first frame (`kind` "frame") or take ("take") in the background."""
	if not is_configured("vision"):
		return
	subject = _subject(
		frappe.db.get_value(
			"Shot", shot_name, ["keyframe_artifact", "selected_output_asset_version"], as_dict=True
		),
		kind,
	)
	frappe.db.set_value(
		"Shot", shot_name, {"consistency_status": "Checking", "consistency_notes": ""}, update_modified=False
	)
	# One job per frame or take: a redrawn frame gets its own check even while an earlier one is still queued.
	frappe.enqueue(
		"joymedia.services.review.consistency.check_scene",
		queue="joymedia_render",
		timeout=1800,
		job_id=f"joymedia-consistency-{shot_name}-{kind}-{subject}",
		deduplicate=True,
		enqueue_after_commit=True,
		shot_name=shot_name,
		kind=kind,
		user=frappe.session.user,
		subject=subject,
	)


def _subject(shot, kind):
	"""What is being checked: the frame's artifact or the take's asset version."""
	return (shot.keyframe_artifact if kind == "frame" else shot.selected_output_asset_version) or ""


def check_scene(shot_name, kind, user, subject=None):
	"""Background job: judge the scene, then pass it, redo it, or mark it for review."""
	frappe.set_user(user)
	shot = frappe.get_doc("Shot", shot_name)
	if subject is not None and _subject(shot, kind) != subject:
		return  # the frame or take was replaced meanwhile; its own check follows
	# Bind every later write to the evidence and direction read before vision I/O.
	shot._consistency_evidence = {
		key: shot.get(key)
		for key in (
			"keyframe_artifact",
			"keyframe_status",
			"selected_output_asset_version",
			"generation_prompt",
			"motion_plan_json",
			"consistency_retries",
		)
	}
	report = None
	if kind == "frame" and shot.keyframe_artifact:
		from joymedia.services.review.admission import report_for

		attempt = frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "generation_attempt")
		report = report_for(attempt) if attempt else None
		if report and report.get("review_only"):
			unconfirmed = [
				r["claim"].rstrip(". ")
				for r in report.get("results") or []
				if str(r.get("id")).startswith("opening.") and r.get("verdict") == "uncertain"
			]
			if unconfirmed:
				return _record(
					shot,
					"Needs Review",
					f"Check that the picture shows: {'; '.join(unconfirmed)}. Automatic screening could not confirm it.",
				)
	try:
		checks = (frame_checks if kind == "frame" else take_checks)(shot)
		if not checks:
			if kind == "frame" and report and report.get("review_only"):
				return _record(
					shot,
					"Needs Review",
					"Geometry qualification remains uncertain; no visual evidence was available to clear it.",
				)
			return _record(shot, "Not Checked", "No visual evidence was available for this check.")
		failures = run_checks(checks)
	except Exception as exc:
		frappe.logger("joymedia.consistency").warning("Consistency check of %s failed: %s", shot_name, exc)
		return _record(shot, "Not Checked", f"The automatic check could not run: {str(exc)[:200]}")
	if kind == "frame":
		from joymedia.services.review.physical_audit import frame_findings

		frame = (
			frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
			if shot.keyframe_artifact
			else None
		)
		if not frame:
			if not failures:
				if report and report.get("review_only"):
					return _record(
						shot,
						"Needs Review",
						"Geometry qualification remains uncertain; the first-frame image is unavailable for physical review.",
					)
				return _record(
					shot, "Not Checked", "The first-frame image is unavailable for physical review."
				)
		else:
			try:
				failures.extend(
					frame_findings(frappe.get_doc("Media Project", shot.media_project), shot, frame)
				)
			except Exception as exc:
				frappe.logger("joymedia.consistency").warning(
					"Physical audit of %s failed: %s", shot_name, exc
				)
				if not failures:
					if report and report.get("review_only"):
						return _record(
							shot,
							"Needs Review",
							"Geometry qualification remains uncertain; the physical review could not run.",
						)
					return _record(
						shot,
						"Not Checked",
						"The physical review could not run; support and placement remain unverified.",
					)
	if not failures:
		if kind == "frame" and report and report.get("review_only"):
			return _record(
				shot,
				"Needs Review",
				"Geometry qualification remains uncertain; this frame is suitable only for an automatic preview.",
			)
		return _record(shot, "Passed", "")
	notes = "; ".join(failures)[:900]
	from joymedia.services.scene.contract import read_contract

	critical_geometry = any(
		reason.startswith(
			(
				"Critical geometry:",
				"Critical framing:",
				"Critical prop:",
				"Critical identity:",
				"Critical style:",
			)
		)
		for reason in failures
	)
	if kind == "take" and _automatic_preview_in_progress(shot.media_project) and not critical_geometry:
		# Keep subjective findings visible on the assembled draft. Clear physical
		# support failures still receive the normal bounded automatic retry.
		return _record(shot, "Needs Review", notes)
	if not critical_geometry and (
		read_contract(shot.get("motion_plan_json"), shot.get("duration_seconds"))
		or any(reason.startswith("Physical staging review:") for reason in failures)
	):
		# These new relational/order questions are advisory until calibrated for
		# the configured judge. Never spend GPU retries on an uncalibrated verdict.
		return _record(shot, "Needs Review", notes)
	if (
		kind == "take"
		and shot.selected_output_asset_version
		and frappe.db.get_value(
			"Asset Version", shot.selected_output_asset_version, "preservation_evidence_json"
		)
	):
		# A generic redraw discards authored tracking/masks and reintroduces label
		# drift. Report the concern, never silently replace a source-art repair.
		return _record(shot, "Needs Review", notes)
	if kind == "frame" and shot.get("keyframe_status") == "Approved":
		# A delayed machine check may report a concern, but cannot replace the
		# frame a person already approved and a video may already be using.
		return _record(shot, "Needs Review", notes)
	limit = MAX_FRAME_REDOS if kind == "frame" else MAX_TAKE_REDOS
	if int(shot.consistency_retries or 0) >= limit:
		return _record(shot, "Needs Review", notes)
	if _record(shot, REDRAW if kind == "frame" else REDO, notes) is False:
		return
	redo_waiting(shot.media_project)


REDRAW, REDO = "Redrawing", "Redoing"
ACTIVE_RUN = ("Draft", "Queued", "Running")


def redo_waiting(project_name):
	"""Start one run for every scene waiting for an automatic redo, when the project has no run going.

	One run per check let several runs write the same records at once and fail (MariaDB 1020); batched like "Draw all
	first frames", the redos run one after another. Called after each check and whenever a run of the project ends.
	"""
	from joymedia.services.generation.takes import _ensure_scene_free, _start_takes_run
	from joymedia.services.keyframes.stage import generate_keyframes

	if _automatic_preview_in_progress(project_name):
		# The batch owns redraw budgets, correction prompts and run lineage.
		# A held batch must not acquire competing, untracked replacement runs.
		return

	lock = f"joymedia-redo-{project_name}"
	if not frappe.db.sql("select get_lock(%s, 30)", lock)[0][0]:
		return
	try:
		if frappe.db.exists("Generation Run", {"media_project": project_name, "status": ["in", ACTIVE_RUN]}):
			return  # the next one starts when this run ends
		for status, kind in ((REDRAW, "frame"), (REDO, "take")):
			names = frappe.get_all(
				"Shot",
				filters={"media_project": project_name, "is_removed": 0, "consistency_status": status},
				pluck="name",
				order_by="shot_number asc",
			)
			if not names:
				continue
			# Admission can reject a replacement before it produces an artifact,
			# so consistency_retries never advances. Bound consecutive failed native
			# tasks as well, otherwise the same bad input can occupy the GPU forever.
			limit = MAX_FRAME_REDOS if kind == "frame" else MAX_TAKE_REDOS
			eligible = []
			for name in names:
				recent = frappe.get_all(
					"Generation Task",
					filters={"shot": name},
					fields=["status"],
					order_by="creation desc",
					limit_page_length=limit,
				)
				if len(recent) >= limit and all(row.status == "Failed" for row in recent):
					frappe.db.set_value(
						"Shot",
						name,
						{
							"consistency_status": "Needs Review",
							"consistency_notes": (
								(frappe.db.get_value("Shot", name, "consistency_notes") or "")
								+ "; automatic replacement stopped after repeated admission failures; revise the source frame or scene"
							)[:1000],
						},
						update_modified=False,
					)
				else:
					eligible.append(name)
			if not eligible:
				frappe.db.commit()
				continue
			names = eligible
			try:
				if kind == "frame":
					generate_keyframes(project_name, names, automatic=True)
				else:
					project = frappe.get_doc("Media Project", project_name)
					for name in names:
						_ensure_scene_free(project, frappe.get_doc("Shot", name))
					_start_takes_run(project, names)
			except Exception as exc:
				frappe.db.rollback()
				for name in names:
					notes = frappe.db.get_value("Shot", name, "consistency_notes") or ""
					frappe.db.set_value(
						"Shot",
						name,
						{
							"consistency_status": "Needs Review",
							"consistency_notes": f"{notes}; it could not be redone automatically: {str(exc)[:200]}"[
								:1000
							],
						},
						update_modified=False,
					)
				frappe.db.commit()
			return
	finally:
		frappe.db.sql("select release_lock(%s)", lock)


def _record(shot, status, notes):
	expected = getattr(shot, "_consistency_evidence", None)
	if expected is not None:
		# Do not hold DB locks while calling a vision endpoint. Acquire a fresh
		# short snapshot only for promotion; late checks cannot approve a new take.
		frappe.db.commit()
		row = frappe.db.sql(
			"select keyframe_artifact, keyframe_status, selected_output_asset_version, generation_prompt, motion_plan_json, consistency_retries "
			"from `tabShot` where name=%s for update",
			shot.name,
			as_dict=True,
		)
		if not row or any(row[0].get(k) != v for k, v in expected.items()):
			frappe.db.commit()
			return False
	values = {"consistency_status": status, "consistency_notes": notes}
	if status in (REDRAW, REDO):
		values["consistency_retries"] = int(shot.consistency_retries or 0) + 1
	frappe.db.set_value("Shot", shot.name, values, update_modified=False)
	frappe.db.commit()
	publish_project_event(shot.media_project, PROJECT_UPDATED, {"doctype": "Shot", "shot": shot.name})
	return True


def reset_redos(shot_name):
	"""A person asked for this frame or take: the automatic redos start again from zero."""
	frappe.db.set_value("Shot", shot_name, "consistency_retries", 0, update_modified=False)


def _cast_size(shot):
	rows = [
		row
		for row in shot.generation_inputs or []
		if frappe.scrub(row.reference_role or "") in ("character", "person", "people", "talent")
	]
	versions = [row.get("asset_version") for row in rows if row.get("asset_version")]
	identities = (
		{
			row.asset_version: row.identity_key
			for row in frappe.get_all(
				"Project Reference",
				filters={"parent": shot.media_project, "asset_version": ["in", versions]},
				fields=["asset_version", "identity_key"],
			)
		}
		if versions
		else {}
	)
	# Several approved views of one identity are still one cast member.
	return len(
		{
			identities.get(row.get("asset_version")) or row.get("asset_version") or f"unbound-{index}"
			for index, row in enumerate(rows)
		}
	)


def _opening_action(shot):
	"""The first sentence of what the scene shows, as the video model is told (no camera or audio lines)."""
	from joymedia.services.project.context import scene_direction

	action = scene_direction(shot.generation_prompt)["action"]
	return re.split(r"(?<=[.!?])\s+", action)[0].strip() if action else ""


COUNT = (
	"How many distinct foreground people or animal actors are established by visible evidence? "
	"Count actors, not body parts. Two hands, arms, paws or wings may belong to one actor and are not two actors "
	"merely because they have different positions or actions. Count the minimum distinct actors actually "
	"established by the visible anatomy; do not invent offscreen owners. "
	"Rendered, animated and cartoon actors DO count, just like photographic actors. "
	"Do not count products themselves or flat characters printed on packaging, a poster or a photograph within the scene. "
	"Return a JSON object with count set to the observed nonnegative integer and reason explaining the visible evidence. Do not use a sample or default count."
)
# A cast of illustrated characters acts alone: a human hand or arm is a stranger the image or video model added.
# Asked about the frame's edge: this model misses a stranger's arm when asked "is there a human hand?" but sees one
# reaching in from outside the frame. This heuristic is not an anatomy certificate.
OUTSIDER = (
	"Does a real human person, human hand, fingers or arm appear physically in this picture, "
	"including a partial hand reaching in from any edge? A hand alone counts. "
	"Do not count illustrated animal paws or a person printed on packaging or a photograph. "
	"Return a JSON object with answer set to true, false, or null for uncertainty, and reason explaining the evidence."
)

UNSUPPORTED_CAST = (
	"Does the physical character clearly stand or sit ON TOP OF the advertised product package "
	"itself, instead of being supported by the floor or a proper seat? Answer true only for a "
	"clearly visible violation. If support is cropped, hidden or uncertain, answer false. "
	"Return JSON with answer boolean and reason."
)
ACTOR_SUPPORT = (
	"The required opening is: {opening}. Is the actor visibly and plausibly supported by the "
	"authored seat or floor, at a height that permits the stated interaction? Answer true when the "
	"visible contact and furniture relationship are physically coherent, false only for a clear "
	"contradiction such as floating, intersecting furniture, or sitting on the work surface instead "
	"of the seat. Answer null if the support is cropped or unclear. Return JSON with answer and "
	"a reason describing the contact and support."
)
ACTOR_ON_TABLETOP = (
	"Is any part of the physical actor visibly standing, sitting, or bearing weight directly on "
	"the TOP SURFACE of a table, desk, counter or other work surface instead of the authored floor "
	"or seat? Identify visible foot or body contact points. Answer true only for clear contact, "
	"false when the actor is behind or beside the furniture, or null if contact is hidden. "
	"Return a JSON object with answer set to true, false, or null and a reason."
)
PRODUCT_TABLE_SCALE = (
	"Is the advertised retail package clearly implausibly large relative to its actual supporting table at the same depth? "
	"A foreground package and a background table cannot be compared by screen width. "
	"A package occupying half a small table is not by itself a defect; do not invent physical dimensions. "
	"Answer true only when both widths can be compared and the scale is clearly implausible; "
	"false when proportionate, or null when the table is cropped or perspective prevents comparison. "
	"Return a JSON object with answer set to true, false, or null and a reason with estimated ratio."
)
FULL_BODY_IN_DETAIL = (
	"Does this image clearly show the entire or nearly entire character body including both feet? "
	"Return a JSON object with answer set to true, false, or null for uncertainty, "
	"and reason explaining visible evidence."
)
PRODUCT_SUPPORT = (
	"Judge ONLY the advertised retail product package, not the actor. Does that package have a physically credible "
	"visible support consistent with this opening direction: {opening}? Its base should contact a table or floor "
	"over a stable area, or a visible paw/hand should clearly grip and bear its weight. "
	"A package projecting past an edge without a clear load-bearing grip is unsupported. A product on the "
	"floor does not satisfy a direction placing it on a table. If the retail package clearly rests on its authored table or floor, answer true "
	"even when the actor does not touch it. Never use the actor's posture as evidence about package support. "
	"Return JSON with answer true, false, or "
	"null for uncertainty, and reason explaining visible evidence."
)
PRODUCT_PERSPECTIVE = (
	"Judge only the advertised retail package and the surface that physically supports it. "
	"Do its visible base, side edges and contact shadow agree with the supporting table or floor plane "
	"and the scene camera perspective? If a paw carries it, judge whether the package orientation and "
	"load-bearing paw contact agree instead. Answer false for a clear pasted-on, skewed or floating "
	"package whose perspective contradicts its support. Answer null if the relevant edges or support "
	"are cropped or hidden. Return JSON with answer and a reason naming visible evidence."
)
HELD_PRODUCT_CONTACT = (
	"Inspect the advertised product's actual support in this opening: {opening}. "
	"Does the product have visible, credible contact with the actor's paw or another physical support? "
	"A product visibly resting on a table or floor is supported even when no paw touches it. "
	"Answer false when the product clearly floats in front of the actor without contact; "
	"answer null when the contact is cropped or hidden. Return JSON with answer true, false, or null "
	"and a reason describing the contact."
)
UNDECLARED_HELD_PACKAGE = (
	"Does the actor clearly hold a rigid printed retail package or product container that is "
	"absent from this required opening composition: {opening}? Answer true only if the actor "
	"clearly holds such an extra physical object; a loose sheet, plain cloth, background package, "
	"or artwork printed in the setting does not count. Return JSON with answer true, false, or "
	"null for uncertainty, and reason explaining visible evidence."
)
SOURCE_ONLY_PROP = (
	"Does this picture visibly include any of these source-only held props: {props}? "
	"They are not part of the authored opening composition. Do not count worn accessories or "
	"objects explicitly required by the opening. Return JSON answer true only if one of the named "
	"separate props is clearly present, false if absent, or null if uncertain, with a reason."
)
PAPER_MATERIAL = (
	"The authored subject is a paper or tissue sheet. Does the visible sheet look like flexible, matte, "
	"fibrous paper rather than shiny metal foil, plastic film, glass, or a rigid slab? Judge only a clearly "
	"visible sheet; answer null if its surface is too small or obscured to assess. Return JSON with answer "
	"true, false, or null and a reason naming the visible material cues."
)
ABSORPTION_PROGRESS = (
	"Read these video frames in time order. Does the authored absorbent surface visibly take the liquid into its material, "
	"with free-standing drops or a puddle decreasing while the surface darkens or wicks? Answer false if the liquid "
	"mainly grows into or remains a reflective puddle on top. Answer null if the surface or liquid is not visible enough "
	"to decide. Return JSON with answer true, false, or null and a reason describing the observed change."
)


def _paper_sheet_detail(shot):
	"""Material checks belong on authored paper-sheet inserts, not every retail package."""
	from joymedia.services.planning.shot_structure import structure_for

	structure = structure_for(shot)
	if not structure or structure["framing"] not in {"close_up", "extreme_close_up"}:
		return False
	direction = " ".join(
		str(shot.get(field) or "") for field in ("start_state", "image_prompt", "generation_prompt")
	)
	return bool(
		re.search(
			r"\b(?:paper|tissue|napkin)\s+(?:sheet|surface|texture|fibers?)\b|\b(?:sheet|surface|texture)\s+of\s+(?:paper|tissue)\b",
			direction,
			re.I,
		)
	)


def _illustrated_cast(shot):
	"""Whether a frame has no authorized real person, including product-only inserts."""
	roles = [frappe.scrub(row.reference_role or "") for row in shot.generation_inputs or []]
	return any(role in ("character", "product") for role in roles) and not any(
		role in ("person", "people", "talent") for role in roles
	)


def shows(action, sequence=False):
	where = "these frames, read left to right and top to bottom," if sequence else "this picture"
	return (
		f'Does {where} clearly show this: "{action}"? Answer true only if it is clearly visible. '
		"Return a JSON object with answer set to true if visibly supported, false if visibly contradicted, or null if hidden or ambiguous, and reason explaining the evidence."
	)


def panels(count):
	return f"Is this picture a split screen of {count} separate panels stacked top to bottom? Return a JSON object with answer set to true, false, or null for uncertainty, and reason explaining the evidence."


def shows_start(description):
	return (
		f'Is this a plausible starting frame for this scene direction: "{description}"? '
		"Evaluate visible starting positions and objects. Future movements, changes, intentions, feelings and thoughts "
		"need not have happened yet and cannot be inferred from a still image. "
		"Return a JSON object with answer set to true if visibly supported, false if visibly contradicted, or null if hidden or ambiguous, and reason explaining the evidence."
	)


def frame_checks(shot):
	"""[(picture, question, expected answer, what a failure means)] for the scene's first frame."""
	from joymedia.services.keyframes.locations import shot_views

	file_url = (
		frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
		if shot.keyframe_artifact
		else None
	)
	if not file_url:
		return []
	views = shot_views(shot)
	checks = []
	cast = 0
	if views:
		checks.append(
			(
				file_url,
				panels(len(views)),
				True,
				f"the frame is not split into the sheet's {len(views)} views",
			)
		)
	else:
		cast = _cast_size(shot)
		if cast:
			checks.append(
				(
					file_url,
					COUNT,
					cast,
					f"Critical geometry: the frame does not show exactly the scene's {cast} character(s)",
				)
			)
		action = shot.get("start_state") or shot.get("image_prompt") or _opening_action(shot)
		if action:
			checks.append(
				(
					file_url,
					shows_start(action),
					True,
					f'the frame is inconsistent with its starting direction: "{action}"',
				)
			)
	if _illustrated_cast(shot):
		checks.append(
			(
				file_url,
				OUTSIDER,
				False,
				"Critical prop: a human hand, arm or person appears; only the cast may act",
			)
		)
	if cast:
		from joymedia.services.planning.prompts import source_prop_exclusions

		excluded_props = source_prop_exclusions(shot, frappe.get_doc("Media Project", shot.media_project))
		if excluded_props:
			checks.append(
				(
					file_url,
					SOURCE_ONLY_PROP.format(props=", ".join(excluded_props)),
					False,
					"Critical prop: a source-only held prop was added to the authored opening",
				)
			)
		from joymedia.services.planning.shot_structure import structure_for

		actor_structure = structure_for(shot)
		if actor_structure and actor_structure["framing"] not in {"close_up", "extreme_close_up"}:
			checks.append(
				(
					file_url,
					ACTOR_SUPPORT.format(
						opening=(shot.get("start_state") or shot.get("image_prompt") or "")[:280]
					),
					True,
					"Critical geometry: actor's seat or floor contact contradicts the authored scene",
				)
			)
			if re.search(
				r"\b(?:table|desk|counter)\b",
				" ".join(str(shot.get(field) or "") for field in ("start_state", "image_prompt")),
				re.I,
			):
				checks.append(
					(
						file_url,
						ACTOR_ON_TABLETOP,
						False,
						"Critical geometry: actor bears weight on a tabletop instead of the floor or seat",
					)
				)
	from joymedia.services.planning.shot_structure import structure_for

	structure = structure_for(shot)
	if _paper_sheet_detail(shot):
		checks.append(
			(
				file_url,
				PAPER_MATERIAL,
				True,
				"Critical prop: paper or tissue sheet has an implausible material",
			)
		)
	has_product = any(
		frappe.scrub(row.reference_role or "") == "product" for row in shot.generation_inputs or []
	)
	if has_product:
		authored_opening = " ".join(
			str(shot.get(field) or "").split("Product orientation is locked", 1)[0]
			for field in ("start_state", "image_prompt")
		)
		if re.search(
			r"\b(?:pack|package|box)\b",
			authored_opening,
			re.I,
		) and re.search(
			r"\b(?:table|desk|counter)\b",
			authored_opening,
			re.I,
		):
			checks.append(
				(
					file_url,
					PRODUCT_TABLE_SCALE,
					False,
					"Critical geometry: handheld product scale is implausible relative to its table",
				)
			)
		if _cast_size(shot):
			checks.append(
				(
					file_url,
					UNSUPPORTED_CAST,
					False,
					"Critical geometry: character stands on the advertised product",
				)
			)
		opening = shot.get("start_state") or shot.get("image_prompt") or ""
		if opening:
			checks.append(
				(
					file_url,
					PRODUCT_SUPPORT.format(opening=opening[:280]),
					True,
					"Critical geometry: advertised product is not on its authored support",
				)
			)
			checks.append(
				(
					file_url,
					PRODUCT_PERSPECTIVE,
					True,
					"Physical staging review: advertised product perspective may not align with its physical support",
				)
			)
			if re.search(r"\b(hold|holding|held|grasp|grasping|carry|carrying)\b", opening, re.I):
				checks.append(
					(
						file_url,
						HELD_PRODUCT_CONTACT.format(opening=opening[:280]),
						True,
						"Critical geometry: held product lacks visible paw or surface contact",
					)
				)
	elif (
		_cast_size(shot)
		and (shot.get("image_prompt") or shot.get("start_state"))
		and (not structure or structure["framing"] not in {"close_up", "extreme_close_up"})
	):
		checks.append(
			(
				file_url,
				UNDECLARED_HELD_PACKAGE.format(
					opening=(shot.get("image_prompt") or shot.get("start_state"))[:280]
				),
				False,
				"Critical prop: actor holds an undeclared retail package instead of the authored object",
			)
		)
	if cast and structure and structure["framing"] in {"close_up", "extreme_close_up"}:
		checks.append(
			(
				file_url,
				FULL_BODY_IN_DETAIL,
				False,
				"Critical framing: full character body appears in a close product/action detail",
			)
		)
	from joymedia.services.scene.contract import opening_claims

	for claim in opening_claims(shot.get("motion_plan_json"), shot.get("duration_seconds")):
		checks.append((file_url, shows_start(claim), True, "Physical staging review: " + claim))

	return checks


def take_checks(shot):
	"""The checks for the scene's take, on frames sampled through it."""
	from joymedia.services.keyframes.locations import shot_views

	file_url = (
		frappe.db.get_value("Asset Version", shot.selected_output_asset_version, "file")
		if shot.selected_output_asset_version
		else None
	)
	if not file_url:
		return []
	from joymedia.services.scene.contract import read_contract

	contract = read_contract(shot.get("motion_plan_json"), shot.get("duration_seconds"))
	frames = sample_frames(frappe.get_doc("File", {"file_url": file_url}).get_full_path(), TAKE_SAMPLES)
	checks = []
	# Contract review is additive. Returning here used to bypass cast and outsider
	# checks precisely on the structured scenes that need them most.
	if contract:
		checks.append(temporal_check(shot, file_url))
	cast = 0 if shot_views(shot) else _cast_size(shot)
	for number, frame in enumerate(frames, 1):
		if cast:
			# At most: a close-up of an object rightly shows nobody; more is someone appearing or a duplicate.
			checks.append(
				(
					frame,
					COUNT,
					AtMost(cast),
					f"frame {number} of {len(frames)} shows more than the scene's {cast} character(s)",
				)
			)
	from joymedia.services.planning.shot_structure import structure_for

	structure = structure_for(shot)
	if _paper_sheet_detail(shot):
		checks.append(
			(
				contact_sheet(frames),
				PAPER_MATERIAL,
				True,
				"Critical prop: moving paper or tissue sheet has an implausible material",
			)
		)
	if cast and structure and structure["framing"] not in {"close_up", "extreme_close_up"}:
		opening = (shot.get("start_state") or shot.get("image_prompt") or "")[:280]
		for number in (0, len(frames) - 1):
			checks.append(
				(
					frames[number],
					ACTOR_SUPPORT.format(opening=opening),
					True,
					f"frame {number + 1} has implausible actor support or seat contact",
				)
			)
	action = scene_action(shot)
	if re.search(r"\babsorb(?:s|ed|ing|ent|ency|tion)?\b", action or "", re.I):
		checks.append(
			(
				contact_sheet(frames),
				ABSORPTION_PROGRESS,
				True,
				"Critical prop: liquid pools instead of visibly absorbing",
			)
		)
	if action and not shot_views(shot):
		checks.append(
			(
				contact_sheet(frames),
				shows(action, sequence=True),
				True,
				f'the clip does not show what the sheet describes: "{action}"',
			)
		)
	if _illustrated_cast(shot):
		checks.append(
			(
				contact_sheet(frames),
				OUTSIDER,
				False,
				"Critical prop: a human hand, arm or person appears in the clip; only the cast may act",
			)
		)
	from joymedia.services.scene.contract import review_questions

	for claim, question in review_questions(shot.get("motion_plan_json"), shot.get("duration_seconds")):
		checks.append(
			(
				contact_sheet(frames),
				question + " If occluded, ambiguous or not sampled, answer null. "
				'Return only JSON: {"answer": null, "reason": "visible evidence or uncertainty"}',
				True,
				"Physical staging review: " + claim,
			)
		)
	return checks


def scene_action(shot):
	from joymedia.services.project.context import scene_direction

	return scene_direction(shot.generation_prompt)["action"]


def contact_sheet(frames):
	"""The sampled frames tiled two by two in one picture (the model reads one picture per question)."""
	from PIL import Image

	pictures = [Image.open(io.BytesIO(frame)).convert("RGB") for frame in frames]
	width, height = pictures[0].size
	sheet = Image.new("RGB", (width * 2, height * ((len(pictures) + 1) // 2)), "white")
	for index, picture in enumerate(pictures):
		sheet.paste(picture.resize((width, height)), ((index % 2) * width, (index // 2) * height))
	output = io.BytesIO()
	sheet.save(output, "PNG")
	return output.getvalue()


def sample_frames(video_path, count):
	"""`count` frames spread evenly through a video, as PNG bytes (the first one at the start)."""
	duration = float(
		subprocess.run(
			["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
			check=True,
			capture_output=True,
			text=True,
			timeout=60,
		).stdout.strip()
		or 0
	)
	frames = []
	with tempfile.TemporaryDirectory() as folder:
		for index in range(count):
			moment = max(0, duration - 1 / 24) * index / max(1, count - 1)
			target = Path(folder) / f"{index}.png"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-ss",
					f"{moment:.3f}",
					"-i",
					str(video_path),
					"-frames:v",
					"1",
					str(target),
				],
				check=True,
				capture_output=True,
				timeout=60,
			)
			frames.append(target.read_bytes())
	return frames


class AtMost(int):
	"""An expected count that may be lower but not higher."""


def run_checks(checks):
	"""Ask each check's question about its picture; returns what failed. An unclear answer fails: unchecked is not passed."""
	failures = []
	for check in checks:
		if isinstance(check, SequenceCheck):
			report = run_temporal_check(check)
			failures.extend(
				"Physical staging review: "
				+ row["claim"]
				+ " ("
				+ row["verdict"]
				+ ": "
				+ row["reason"]
				+ ")"
				for row in report["results"]
				if row["verdict"] != "supported"
			)
			continue
		picture, question, expected, meaning = check
		counted = isinstance(expected, int) and not isinstance(expected, bool)
		field = "count" if counted else "answer"
		answer = ask(
			picture,
			question
			+ " First describe the concrete visible evidence in reason, then derive the result from it.",
			schema={
				"type": "object",
				"additionalProperties": False,
				"required": ["reason", field],
				"properties": {
					"reason": {"type": "string", "minLength": 1},
					field: {"type": ["integer", "null"], "minimum": 0}
					if counted
					else {"type": ["boolean", "null"]},
				},
			},
		)
		value = _value(answer.get("count") if counted else answer.get("answer"))
		matches = (
			type(value) is int and value <= expected and value >= 0
			if isinstance(expected, AtMost)
			else (
				type(value) is int and value == expected
				if counted
				else type(value) is bool and value is expected
			)
		)
		matches = matches and isinstance(answer.get("reason"), str) and bool(answer["reason"].strip())
		if not matches:
			reason = str(answer.get("reason") or "").strip()
			failures.append(meaning + (f" ({reason})" if reason else ""))
	return list(dict.fromkeys(failures))


def locate(image_bytes, thing):
	"""The box (left, top, right, bottom, in the picture's pixels) of `thing` in the picture, or None: the model's own
	grounding (the configured vision service answers boxes in the pixels of the picture it was sent). A box covering almost nothing or most
	of the picture is not trusted."""
	from PIL import Image

	if not is_configured("vision"):
		return None
	configured = endpoint("vision")
	with Image.open(io.BytesIO(image_bytes)) as picture:
		width, height = picture.size
	scale = max(width, height) / IMAGE_EDGE if max(width, height) > IMAGE_EDGE else 1
	try:
		response = _post_visual_request(
			f"{configured.base_url}/chat/completions",
			json={
				"model": configured.model,
				"messages": [
					{
						"role": "user",
						"content": [
							{"type": "image_url", "image_url": {"url": _data_url(image_bytes)}},
							{
								"type": "text",
								"text": f'Locate {thing} in this image. Return only JSON: {{"bbox_2d": [x1, y1, x2, y2]}}',
							},
						],
					}
				],
				**sampling("vision_geometry"),
			},
			timeout=(10, configured.timeout),
		)
		response.raise_for_status()
		found = re.search(
			r'"bbox_2d"\s*:\s*\[([^\]]+)\]', response.json()["choices"][0]["message"]["content"]
		)
		left, top, right, bottom = (float(v) * scale for v in found.group(1).split(",")[:4])
	except Exception:
		return None
	left, top, right, bottom = max(0, left), max(0, top), min(width, right), min(height, bottom)
	area = max(0, right - left) * max(0, bottom - top) / (width * height)
	return (round(left), round(top), round(right), round(bottom)) if 0.005 <= area <= 0.4 else None


def _value(value):
	"""A JSON answer as a bool or int, whichever way the model wrote it ("2", "true")."""
	text = str(value).strip().casefold()
	if text in ("true", "yes"):
		return True
	if text in ("false", "no"):
		return False
	return int(text) if text.isdigit() else value


# A vision answer is a short JSON object; silence this long means the request was
# lost in the GPU tunnel, not that the model is still working.
VISION_IDLE_SECONDS = 60


class _StreamedAnswer:
	"""The completed stream, read like the plain response callers already use."""

	def __init__(self, response, content):
		self.status_code = response.status_code
		self._response = response
		self._content = content

	def raise_for_status(self):
		self._response.raise_for_status()

	def json(self):
		return {"choices": [{"message": {"content": self._content}}]}


def _post_visual_request(url, *, json=None, timeout=(10, 120)):
	"""Retry a dropped read-only observation, never a judgment or media render."""
	from joymedia.services.runtime.streaming import post_streamed

	for attempt in range(3):
		try:
			response, content = post_streamed(
				url,
				json or {},
				idle_seconds=min(VISION_IDLE_SECONDS, timeout[1]),
				deadline_seconds=timeout[1],
			)
			return response if content is None else _StreamedAnswer(response, content)
		except (requests.ConnectionError, requests.Timeout):
			if attempt == 2:
				raise
			time.sleep(5 * (attempt + 1))


def ask(picture, question, configured=None, *, max_edge=IMAGE_EDGE, schema=None):
	"""One picture, one question, a JSON answer."""
	configured = configured or endpoint("vision")
	pictures = picture if isinstance(picture, (list, tuple)) else [picture]
	if not 1 <= len(pictures) <= 4:
		raise ValueError("Visual observations require one to four images.")
	response = _post_visual_request(
		f"{configured.base_url}/chat/completions",
		json={
			"model": configured.model,
			"messages": [
				{
					"role": "user",
					"content": [
						*(
							{"type": "image_url", "image_url": {"url": _data_url(image, max_edge=max_edge)}}
							for image in pictures
						),
						{"type": "text", "text": question},
					],
				}
			],
			**(
				structured_response(configured, schema, "visual_observation")
				if schema is not None
				else {"response_format": {"type": "json_object"}}
			),
			**sampling("vision_observation"),
		},
		timeout=(10, configured.timeout),
	)
	response.raise_for_status()
	answer = json.loads(response.json()["choices"][0]["message"]["content"])
	return answer if isinstance(answer, dict) else {}


def _data_url(image, *, max_edge=IMAGE_EDGE):
	"""A bounded JPEG from a Frappe file URL or PNG bytes.

	Geometry review needs more detail than quick semantic checks. Keep the default
	request small and let that review request a larger, still bounded picture.
	"""
	if type(max_edge) is not int or not IMAGE_EDGE <= max_edge <= 1024:
		raise ValueError("Vision image edge must be between 448 and 1024 pixels.")
	from PIL import Image

	source = (
		io.BytesIO(image)
		if isinstance(image, bytes)
		else frappe.get_doc("File", {"file_url": image}).get_full_path()
	)
	with Image.open(source) as picture:
		picture = picture.convert("RGB")
		picture.thumbnail((max_edge, max_edge))
		buffer = io.BytesIO()
		picture.save(buffer, format="JPEG", quality=85)
	return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def temporal_check(shot, file_url):
	"""Build full-size per-frame evidence at uniform and authored event moments."""
	from joymedia.services.scene.evidence import claims_for, digest, sample_times

	path = Path(frappe.get_doc("File", {"file_url": file_url}).get_full_path())
	probe = json.loads(
		subprocess.run(
			[
				"ffprobe",
				"-v",
				"error",
				"-select_streams",
				"v:0",
				"-show_entries",
				"stream=avg_frame_rate,duration:format=duration",
				"-of",
				"json",
				str(path),
			],
			check=True,
			capture_output=True,
			text=True,
			timeout=60,
		).stdout
	)
	stream = probe["streams"][0]
	numerator, denominator = stream["avg_frame_rate"].split("/")
	fps = float(numerator) / float(denominator)
	duration = float(stream.get("duration") or probe["format"]["duration"])
	moments = sample_times(duration, fps, shot.get("motion_plan_json"))
	pictures, metadata = [], []
	with tempfile.TemporaryDirectory() as folder:
		for index, moment in enumerate(moments):
			target = Path(folder) / f"{index}.png"
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-ss",
					f"{moment:.6f}",
					"-i",
					str(path),
					"-frames:v",
					"1",
					str(target),
				],
				check=True,
				capture_output=True,
				timeout=60,
			)
			data = target.read_bytes()
			pictures.append(data)
			metadata.append({"index": index, "time": moment, "sha256": digest(data)})
	claims = claims_for(shot.get("motion_plan_json"), shot.get("duration_seconds"), scene_action(shot))
	cast = _cast_size(shot)
	if cast:
		claims.append(
			{
				"id": "cast",
				"dimension": "consistency",
				"claim": f"No sampled frame shows more than {cast} foreground actors. Packaging artwork does not count. Actors may legitimately be outside the camera view.",
			}
		)
	if _illustrated_cast(shot):
		claims.append(
			{
				"id": "outsider",
				"dimension": "consistency",
				"claim": "Only the reference illustrated cast acts in this scene; no unrelated real human hand or arm enters the frame.",
			}
		)
	actual_hash = digest(path.read_bytes())
	expected_hash = frappe.db.get_value("Asset Version", shot.selected_output_asset_version, "content_hash")
	if expected_hash and expected_hash != actual_hash:
		raise ValueError("The stored video bytes do not match the immutable asset hash.")
	return SequenceCheck(
		pictures,
		metadata,
		claims,
		{
			"shot": shot.name,
			"asset_version": shot.selected_output_asset_version,
			"source_sha256": actual_hash,
			"direction_sha256": _review_direction_hash(shot),
			"required_claim_ids": [row["id"] for row in claims],
			"duration": duration,
			"fps": fps,
			"opening_state": _opening_state(shot.selected_output_asset_version, pictures[0]),
		},
	)


def run_temporal_check(check, configured=None):
	"""One multimodal request, separate dimension verdicts, exact-media private evidence."""
	from frappe.utils.file_manager import save_file

	from joymedia.services.scene.evidence import (
		MAX_CLAIMS,
		batches,
		digest,
		evaluate,
		merge_observations,
		question,
	)

	if len(check.claims) > MAX_CLAIMS:
		raise ValueError("Too many claims for a bounded temporal review.")
	configured = configured or endpoint("vision")
	reports, raw_answers = [], []
	windows = list(batches(check))
	# Each window is a separate bounded request. A fixed three-minute budget
	# starved later claims on scenes with several contact transitions, even
	# when every request completed normally. Stay within the admission worker's
	# thirty-minute timeout and leave time for identity/count observations.
	budget = min(1200, max(180, configured.timeout * len(windows)))
	deadline = time.monotonic() + budget
	for indices, claims in windows:
		if time.monotonic() >= deadline:
			break  # Unreviewed claims merge as uncertain; no implicit support.
		content = []
		for index in indices:
			meta = check.metadata[index]
			content.extend(
				[
					{"type": "text", "text": f"Frame {meta['index']} at {meta['time']:.3f}s"},
					{"type": "image_url", "image_url": {"url": _data_url(check.pictures[index])}},
				]
			)
		window = SequenceCheck(
			[], check.metadata, claims, {**check.context, "allowed_indices": list(indices)}
		)
		content.append({"type": "text", "text": question(window)})
		schema = {
			"type": "object",
			"additionalProperties": False,
			"required": ["observations"],
			"properties": {
				"observations": {
					"type": "array",
					"minItems": len(claims),
					"maxItems": len(claims),
					"items": {
						"type": "object",
						"additionalProperties": False,
						"required": ["id", "verdict", "frames", "reason"]
						+ (
							["phase_frames"]
							if any(row.get("evidence_kind") == "transition" for row in claims)
							else []
						),
						"properties": {
							"id": {"type": "string", "enum": [row["id"] for row in claims]},
							"verdict": {"type": "string", "enum": ["supported", "violated", "uncertain"]},
							"frames": {
								"type": "array",
								"minItems": 1,
								"maxItems": len(indices),
								"items": {"type": "integer", "enum": list(indices)},
							},
							"reason": {"type": "string"},
							"phase_frames": {
								"type": "object",
								"additionalProperties": False,
								"required": ["before", "during", "after"],
								"properties": {
									phase: {"type": "integer", "enum": list(indices)}
									for phase in ("before", "during", "after")
								},
							},
						},
					},
				}
			},
		}
		response = _post_visual_request(
			f"{configured.base_url}/chat/completions",
			json={
				"model": configured.model,
				"messages": [{"role": "user", "content": content}],
				**structured_response(configured, schema, "temporal_observations"),
				**sampling("vision_observation"),
			},
			timeout=(10, min(configured.timeout, max(1, deadline - time.monotonic()))),
		)
		response.raise_for_status()
		raw = response.json()["choices"][0]["message"]["content"]
		try:
			answer = json.loads(raw)
		except (ValueError, TypeError):
			answer = {}
		reports.append(evaluate(window, answer))
		raw_answers.append(
			{
				"indices": list(indices),
				"claims": [row["id"] for row in claims],
				"response": raw[:3000] if isinstance(raw, str) else "",
			}
		)
	report = merge_observations(check, reports)
	report["judge"] = {
		"model": configured.model,
		"temperature": sampling("vision_observation")["temperature"],
		"max_images_per_request": 4,
		"max_claims_per_request": 1,
		"review_budget_seconds": budget,
	}
	report["windows"] = reports
	report["raw_responses"] = raw_answers
	payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode()
	name = f"temporal-review-{digest(payload)[:20]}.json"
	doctype = check.context.get("evidence_doctype", "Asset Version")
	docname = check.context.get("evidence_name") or check.context["asset_version"]
	# Content-addressed: identical evidence (a deterministic re-check of the same
	# footage) is reused rather than re-saved under a reviewer who may not own it.
	report["evidence_file"] = (
		frappe.db.get_value(
			"File",
			{"file_name": name, "attached_to_doctype": doctype, "attached_to_name": docname},
			"file_url",
		)
		or save_file(name, payload, doctype, docname, is_private=1).file_url
	)
	return report


@frappe.whitelist()
def request_scene_check(project_name, shot_name, expected_take):
	"""Recheck only the take actually shown in this owner's browser."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	frappe.db.sql("select name from `tabShot` where name=%s for update", shot_name)
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw("Shot does not belong to this project.", frappe.PermissionError)
	if not expected_take or shot.selected_output_asset_version != expected_take:
		frappe.throw("The selected take changed. Refresh before checking it.")
	if not is_configured("vision"):
		frappe.throw("The scene review service is unavailable.")
	queue_check(shot.name, "take")
	return {"status": "Checking", "take": expected_take}


@frappe.whitelist()
def get_scene_check_evidence(project_name, shot_name, expected_take):
	"""Read findings only for this project's exact selected take and current direction."""
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw("Shot does not belong to this project.", frappe.PermissionError)
	if not expected_take or shot.selected_output_asset_version != expected_take:
		frappe.throw("The selected take changed. Refresh before reading its check.")
	direction = _review_direction_hash(shot)
	content_hash = frappe.db.get_value("Asset Version", expected_take, "content_hash")
	for row in frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Asset Version",
			"attached_to_name": expected_take,
			"file_name": ["like", "temporal-review-%.json"],
			"is_private": 1,
		},
		pluck="name",
		order_by="creation desc",
		limit=10,
	):
		try:
			report = json.loads(Path(frappe.get_doc("File", row).get_full_path()).read_text())
		except (OSError, ValueError):
			continue
		if (
			report.get("scope") == "scene"
			and report.get("asset_version") == expected_take
			and report.get("shot") == shot_name
			and report.get("source_sha256") == content_hash
			and report.get("direction_sha256") == direction
		):
			return {
				key: report.get(key)
				for key in ["version", "asset_version", "samples", "results", "status", "limitations"]
			}
	return None


def _review_direction_hash(shot):
	from joymedia.services.scene.evidence import digest

	fields = [
		shot.get(key)
		for key in [
			"generation_prompt",
			"motion_plan_json",
			"image_prompt",
			"start_state",
			"duration_seconds",
		]
	]
	references = sorted(
		(row.get("reference_role") or "", row.get("asset_version") or "")
		for row in shot.get("generation_inputs") or []
	)
	return digest(json.dumps([fields, references], ensure_ascii=False).encode())


def _opening_state(version_name, first_picture):
	"""Resolve the exact frozen reference, including derived controls/repairs.

	Never compare an old take against the scene's current editable first frame.
	"""
	from joymedia.services.scene.evidence import compare_opening

	seen = set()
	for _ in range(8):
		if not version_name or version_name in seen:
			return None
		seen.add(version_name)
		version = frappe.get_doc("Asset Version", version_name)
		if not version.source_generation_attempt:
			version_name = version.derived_from
			continue
		task_name = frappe.db.get_value(
			"Generation Attempt", version.source_generation_attempt, "generation_task"
		)
		task = frappe.get_doc("Generation Task", task_name)
		snapshot = frappe.parse_json(
			frappe.db.get_value("Generation Run", task.generation_run, "project_snapshot_json") or "{}"
		)
		shot = next((row for row in snapshot.get("shots", []) if row.get("shot") == task.shot), {})
		artifact = shot.get("keyframe_artifact")
		if not artifact:
			return None  # No explicit frozen opening image for this workflow.
		url = frappe.db.get_value("Generation Artifact", artifact, "frappe_file")
		if not url:
			return {"verdict": "uncertain", "frames": [], "reason": "Frozen opening evidence is unavailable."}
		data = Path(frappe.get_doc("File", {"file_url": url}).get_full_path()).read_bytes()
		return {"artifact": artifact, **compare_opening(data, first_picture)}
	return {
		"verdict": "uncertain",
		"frames": [],
		"reason": "Opening evidence lineage exceeds the bounded lookup.",
	}
