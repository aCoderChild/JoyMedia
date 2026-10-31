"""Pose coverage derived from the complete planned shot list.

This is deliberately model-neutral.  A planner has already interpreted each
shot's action; this pass turns that interpretation plus the selected reference
views into an explicit opening-pose requirement for the image stage.  An image
workflow may satisfy it with ordinary reference conditioning or a registered
pose-control workflow.  The result is stored with the shot, so a video stage
never has to infer an unsupported pose transition from a single source image.
"""

from __future__ import annotations

import json
import re

UPRIGHT = re.compile(
	r"\b(?:stand(?:s|ing)?|walk(?:s|ing)?|run(?:s|ning)?|step(?:s|ping)?|approach(?:es|ing)?|travel(?:s|ling)?|move(?:s|ing)?\s+(?:to|toward|towards|across))\b",
	re.I,
)
STAND_UP = re.compile(r"\b(?:stand(?:s|ing)?|get(?:s|ting)?)\s+up\b", re.I)
SEATED = re.compile(r"\b(?:sit(?:s|ting)?|seated)\b", re.I)
LOW_SUPPORT = re.compile(r"\b(?:kneel(?:s|ing)?|crouch(?:es|ing)?|lie(?:s|lying)?)\b", re.I)
FREE_HANDS = re.compile(
	r"\b(?:both\s+)?(?:paws?|hands?)\s+(?:are\s+)?(?:free|empty|unoccupied)\b"
	r"|\b(?:free|empty|unoccupied)\s+(?:paws?|hands?)\b",
	re.I,
)
HELD_OBJECT = re.compile(r"\b(?:hold(?:s|ing)?|carr(?:y|ies|ying)|grip(?:s|ping)?|clutch(?:es|ing)?)\b", re.I)


LIMB_SUBJECT = re.compile(
	r"\b(?:paws?|hands?|arms?|fingers?|head|feet|foot|legs?|tail)\W*(?:\w+\W+){0,2}$", re.I
)


def _whole_body_upright(text):
	"""An upright or locomotion word whose subject is the character, not a limb ("its paw moves towards ...")."""
	return any(not LIMB_SUBJECT.search(text[: m.start()]) for m in UPRIGHT.finditer(text))


def required_pose(action, structure=None):
	"""Return the opening-body state that makes a shot's first action feasible."""
	text = str(action or "")
	if STAND_UP.search(text) and not re.search(
		r"\b(?:walk|run|travel)\b", text[: STAND_UP.search(text).start()], re.I
	):
		return "seated_supported"
	if SEATED.search(text) and not _whole_body_upright(text):
		return "seated_supported"
	if _whole_body_upright(text) or (structure or {}).get("subject_motion") == "locomotion":
		return "upright_supported"
	if LOW_SUPPORT.search(text):
		return "low_supported"
	if SEATED.search(text):
		return "seated_supported"
	return "preserve_reference_pose"


def source_pose_state(descriptions):
	"""Conservative shared state of the selected visual references."""
	values = [str(value or "") for value in descriptions if str(value or "").strip()]
	if not values:
		return "unknown"
	if all(re.search(r"\b(?:seated|sitting)\b", value, re.I) for value in values):
		return "seated_supported"
	if any(re.search(r"\b(?:standing|walking|upright)\b", value, re.I) for value in values):
		return "mobile_or_upright"
	return "mixed_or_unknown"


def matching_view(selected, current_version, target, pose_by_asset, qualified_by_asset=None):
	"""Find an already supplied view of this identity with the required support.

	An alternate side/back view is useful only when its analyzed pose matches the
	planned action.  Never borrow a pose from another character identity.
	"""
	current = next((row for row in selected if row.get("asset_version") == current_version), None)
	states = {"upright_supported": "mobile_or_upright", "seated_supported": "seated_supported"}
	needed = states.get(target)
	if not current or not needed:
		return None
	current_matches = source_pose_state([pose_by_asset.get(current_version)]) == needed
	identity = current.get("identity_key")
	if not identity:
		return None
	candidates = [
		row
		for row in selected
		if row.get("asset_version") != current_version
		and row.get("identity_key") == identity
		and str(row.get("reference_role") or "").casefold() in {"character", "person"}
		and source_pose_state([pose_by_asset.get(row.get("asset_version"))]) == needed
	]
	# A qualified, prop-free pose is preferable to an uploaded character photo
	# whose separate held prop can contaminate an unrelated scene. Keep an
	# already qualified matching view to avoid needless reference churn.
	qualified_by_asset = qualified_by_asset or {}
	if current_matches and qualified_by_asset.get(current_version):
		return None
	qualified = [row for row in candidates if qualified_by_asset.get(row.get("asset_version"))]
	if qualified:
		candidates = qualified
	elif current_matches:
		return None
	# A side or three-quarter view usually conveys feet and depth more clearly
	# than a rear view when the storyboard did not request a particular angle.
	return next((row for row in candidates if "back" not in str(row.get("label") or "").lower()), None) or (
		candidates[0] if candidates else None
	)


def pose_requirement(action, structure=None, source_poses=(), has_character=True):
	"""Produce a serializable, reviewable requirement for one planned shot."""
	if not has_character:
		return {
			"version": 1,
			"source_pose": "not_applicable",
			"opening_pose": "not_applicable",
			"requires_bridge_keyframe": False,
			"generation_strategy": "product_or_environment_keyframe",
			"constraints": [],
		}
	target = required_pose(action, structure)
	source = source_pose_state(source_poses)
	bridge = source == "seated_supported" and target == "upright_supported"
	constraints = []
	if target == "upright_supported":
		constraints += [
			"show the full lower body and both feet on the visible supporting surface",
			"keep the torso upright with no furniture, table or prop intersecting the body",
		]
	elif target == "seated_supported":
		constraints.append("show the seat or ground that supports the pelvis and feet")
	elif target == "low_supported":
		constraints.append("show the limbs and surface carrying the body weight")
	return {
		"version": 1,
		"source_pose": source,
		"opening_pose": target,
		"requires_bridge_keyframe": bridge,
		"generation_strategy": "reference_conditioned_pose_bridge"
		if bridge
		else "reference_conditioned_keyframe",
		"constraints": constraints,
	}


def keyframe_character_mode(requirement, current_mode=None):
	"""Choose how the opening frame can satisfy a planned pose.

	Exact-art compositing preserves an uploaded cutout pixel-for-pixel, but it
	cannot change that cutout from seated to upright.  A bridge therefore needs
	a reference-conditioned redraw of the character.  Product references remain
	exact-art assets in this mode, so this does not trade away package fidelity
	for pose flexibility.
	"""
	if isinstance(requirement, dict) and requirement.get("requires_bridge_keyframe"):
		from joymedia.services.keyframes.overlay import DRAW

		return DRAW
	return current_mode


def opening_reference_conflicts(shot):
	"""Find clear contradictions between a shot's opening and its image inputs.

	A generated pose is trusted only when it passed the reusable pose qualification.
	An uploaded photo can preserve identity, but a visibly held prop must not be
	used as the body-state reference for a free-paw first frame.
	"""
	import frappe

	opening = " ".join(str(shot.get(key) or "") for key in ("start_state", "image_prompt"))
	if not FREE_HANDS.search(opening):
		return []
	from joymedia.services.planning.pose_assets import _qualified_pose_metadata

	conflicts = []
	for row in shot.get("generation_inputs") or shot.get("references") or []:
		if str(row.get("reference_role") or "").casefold() not in {"character", "person"}:
			continue
		version = row.get("asset_version")
		if not version:
			continue
		analysis = (
			frappe.parse_json(frappe.db.get_value("Asset Version", version, "analysis_json") or "{}") or {}
		)
		qualified = _qualified_pose_metadata(analysis)
		if qualified and not HELD_OBJECT.search(qualified["pose"]):
			continue
		held = analysis.get("held_objects")
		if (
			qualified
			or held not in (None, "", "none", "None", [], {})
			or HELD_OBJECT.search(str(analysis.get("description") or ""))
		):
			conflicts.append(version)
	return conflicts


def assert_opening_character_references(shots):
	"""Stop first-frame rendering when a source contradicts an explicit opening pose."""
	for shot in shots:
		conflicts = opening_reference_conflicts(shot)
		if conflicts:
			raise ValueError(
				f"Scene {shot.get('shot_number') or shot.get('name')}: the opening requires free paws or hands, "
				"but its character reference holds a separate object. Prepare and verify a prop-free "
				"pose of the same character before drawing the first frame."
			)


def annotate_shots(project, shots):
	"""Persist requirements only after the whole project has been planned.

	A separate pass is important: all scenes are known before any image is drawn,
	which lets the storyboard expose each bridge frame as an intermediate output.
	"""
	by_asset = {}
	qualified_by_asset = {}
	for row in project.get("selected_media") or []:
		if str(row.get("reference_role") or "").casefold() not in {"character", "person"}:
			continue
		# Asset analysis is fetched by the caller-compatible Frappe API here rather
		# than copied into the project document.  Keeping this small adapter avoids
		# tying pose planning to a particular image provider.
		try:
			import frappe

			analysis = (
				frappe.parse_json(
					frappe.db.get_value("Asset Version", row.get("asset_version"), "analysis_json") or "{}"
				)
				or {}
			)
		except Exception:
			analysis = {}
		# Re-analysis can describe a generated pose incorrectly. The reviewed
		# qualification is the reusable asset contract and wins when present.
		from joymedia.services.planning.pose_assets import _qualified_pose_metadata

		qualified = _qualified_pose_metadata(analysis)
		by_asset[row.get("asset_version")] = str(
			(qualified or {}).get("pose")
			or ("" if analysis.get("source_asset_version") else analysis.get("pose_and_support"))
			or ""
		)
		qualified_by_asset[row.get("asset_version")] = bool(qualified)
	try:
		import frappe

		automatic = (frappe.parse_json(project.get("storyboard_source_json") or "{}") or {}).get(
			"generation_origin"
		) == "ai_director"
	except (TypeError, ValueError):
		automatic = False
	last_view_by_identity = {}
	for shot in shots:
		plan = shot.get("motion_plan_json") or {}
		if isinstance(plan, str):
			plan = json.loads(plan or "{}")
		structure = plan.get("shot_structure") or {}
		opening_action = str(((plan.get("actions") or [{}])[0] or {}).get("action") or "")
		opening_description = str(shot.get("image_prompt") or "")
		starting_state = str(shot.get("start_state") or "")
		# The opening still is authoritative when it explicitly stages support;
		# a later walk cannot turn a stand-up transition's first frame upright.
		if SEATED.search(opening_description) and STAND_UP.search(opening_action):
			opening_action = "seated"
		elif (
			not STAND_UP.search(opening_action)
			and required_pose(opening_action, structure) == "preserve_reference_pose"
		):
			# Product handling and reactions often omit a posture verb. Their
			# authored opening state carries the continuity from the previous shot.
			# Bind that state to a qualified view instead of reverting to the
			# canonical uploaded pose for every such scene.
			opening_action = starting_state or opening_description or opening_action
		elif not opening_action:
			opening_action = opening_description + "\n" + str(shot.get("generation_prompt") or "")
		references = shot.get("generation_inputs") or shot.get("references") or []
		character_references = [
			row
			for row in references
			if str(row.get("reference_role") or "").casefold() in {"character", "person"}
		]
		if automatic:
			for row in character_references:
				current = next(
					(
						selected
						for selected in project.get("selected_media") or []
						if selected.get("asset_version") == row.get("asset_version")
					),
					None,
				)
				identity = current.get("identity_key") if current else None
				target = required_pose(opening_action, structure)
				candidate = matching_view(
					project.get("selected_media") or [],
					row.get("asset_version"),
					target,
					by_asset,
					qualified_by_asset,
				)
				if candidate:
					row.asset_version = candidate.get("asset_version")
				elif target == "preserve_reference_pose" and identity in last_view_by_identity:
					row.asset_version = last_view_by_identity[identity]
				if identity:
					last_view_by_identity[identity] = row.get("asset_version")
		poses = [by_asset.get(row.get("asset_version"), "") for row in character_references]
		requirement = pose_requirement(
			opening_action,
			structure,
			poses,
			bool(character_references),
		)
		plan["pose_requirement"] = requirement
		# This is an automatic per-shot route, not a project-wide mode change.
		# It lets the image stage generate the requested supported pose from the
		# character reference, while the overlay keeps product cutouts exact.
		shot.character_mode = keyframe_character_mode(requirement, shot.get("character_mode"))
		shot.motion_plan_json = json.dumps(plan, ensure_ascii=False, separators=(",", ":"))
		shot.save(ignore_permissions=True)
