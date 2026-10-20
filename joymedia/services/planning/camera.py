"""Deterministic camera direction from scene structure, never camera prose.

The first frame owns the actual opening crop. Framing suggestions are for new
keyframes only; an approved frame is never reframed by this policy.
"""

import json
import re

CINEMATIC_PLANNING_RULES = """
Infer only motion_plan.shot_structure from the authored narrative beat.
The application derives camera_intent from that structure; do not generate camera_intent.
The resulting policy chooses one motivated behavior independently of camera prose.
Opening geography or broad acting can use a measured axial push to create a hook; no camera shake.
Locomotion follows at subject pace with persistent environmental landmarks and true parallax.
Grip, extraction, wiping, unfolding and material/contact inspection use locked demonstration coverage.
stage describes the narrative beat, not any incidental hand movement: establish for an opening,
feel for an emotional response, hero for a final product presentation; extract only for extraction.
Detail progression is motivated by what the viewer needs to see, not arbitrary shot-number alternation.
A pull-back/reveal or arc requires reviewed opening AND ending references and allow_reframe=true;
without both supplied endpoints choose a bounded push or locked frame, never invent unseen geometry.
Keep product artwork, contact and required margins legible. Do not move to hide an interaction.
No combined orbit+zoom+tilt or independent sliding background. Ease one continuous move in/out;
settle before the final hold. Cinematic energy means purposeful movement, not constant movement.
"""


def camera_planning_rules(project):
	from joymedia.services.intake.references import brand

	return (
		CINEMATIC_PLANNING_RULES
		if str(brand(project).get("camera_style") or "").strip().lower() == "cinematic"
		else ""
	)


def infer_cinematic_intent(structure, *, opening=False, closing=False):
	"""Deterministic purpose-to-move grammar after semantic shot planning."""
	stage, framing, motion = (structure[k] for k in ("stage", "framing", "subject_motion"))
	precision = stage in {"grip", "extract", "unfold", "inspect", "detail"} or framing == "extreme_close_up"
	if precision:
		behavior, purpose, energy = "locked", "demonstrate", "measured"
	elif motion == "locomotion":
		behavior, purpose, energy = "tracking_backward", "follow", "measured"
	elif opening and framing in {"wide", "full", "medium", "medium_close_up"}:
		behavior, purpose, energy = "push_in", "hook", "brisk"
	elif (stage == "feel" and framing in {"wide", "full", "medium", "medium_close_up"}) or closing:
		behavior, purpose, energy = "push_in", "resolve", "measured"
	else:
		behavior, purpose, energy = "locked", "demonstrate", "measured"
	return {"behavior": behavior, "allow_reframe": False, "purpose": purpose, "energy": energy}


def camera_intent(value):
	if value is None:
		return None
	if not isinstance(value, dict) or set(value) - {"behavior", "allow_reframe", "purpose", "energy"}:
		raise ValueError("Camera intent requires one behavior and optional allow_reframe.")
	if (
		value.get("behavior") not in {"locked", "tracking_backward", "push_in", "pull_back", "arc"}
		or type(value.get("allow_reframe", False)) is not bool
	):
		raise ValueError("Unsupported camera behavior or invalid reframing permission.")
	result = {"behavior": value["behavior"], "allow_reframe": value.get("allow_reframe", False)}
	for name, options in [
		("purpose", {"hook", "follow", "demonstrate", "detail", "reveal", "resolve"}),
		("energy", {"slow", "measured", "brisk"}),
	]:
		if name in value:
			if not isinstance(value[name], str) or value[name] not in options:
				raise ValueError("Unsupported camera " + name + ".")
			result[name] = value[name]
	return result


def camera_plan(shot, project, is_final=False, framing_safety=None, generated_composition=False):
	result = _camera_plan(
		shot,
		project,
		is_final=is_final,
		framing_safety=framing_safety,
		generated_composition=generated_composition,
	)
	if generated_composition:
		result["direction"] = (
			"Generate the authored opening framing with the required action area visible; for a broad moving shot reserve at least ten percent margin around all required subjects. "
			+ result["direction"]
		)
		result["framing_evidence"] = (
			"Generated opening is unverified; review actual coverage and margins after rendering."
		)
	if result["product_focus"]:
		result["direction"] += " Keep the visible product surface and contact area sharp and supported."
		from joymedia.services.planning.shot_structure import structure_for

		structure = structure_for(shot)
		if structure and structure["framing"] in {"close_up", "extreme_close_up"}:
			result["direction"] += (
				" Camera framing alone must not reveal unseen parts merely to show the whole object; a detail view stays a detail. Authored object movement and natural occlusion changes remain allowed."
			)
	return result


def _camera_plan(shot, project, is_final=False, framing_safety=None, generated_composition=False):
	from joymedia.services.planning.framing import allows_push
	from joymedia.services.planning.shot_structure import framing_text, structure_for, visibility_instruction

	structure = structure_for(shot)
	plan = shot.get("motion_plan_json") or {}
	if isinstance(plan, str):
		plan = json.loads(plan)
	refs = shot.get("references") or []
	roles = {str(r.get("reference_role") or r.get("input_role") or "").lower() for r in refs}
	product = "product" in roles
	actor = bool(roles & {"character", "person", "people", "talent"})
	shots = project.get("shots") or []
	position = next(
		(i for i, s in enumerate(shots) if (s.get("shot") or s.get("name")) == shot.get("name")),
		max(0, int(shot.get("shot_number") or 1) - 1),
	)
	closing = is_final or shot.get("handoff_type") == "ending" or bool(shots and position == len(shots) - 1)
	contract = plan.get("scene_contract") or {}
	intent = camera_intent(plan.get("camera_intent"))
	broad_presentation = bool(
		structure
		and intent
		and intent.get("purpose") in {"hook", "reveal", "resolve"}
		and structure["stage"] in {"establish", "present", "feel", "hero"}
		and (
			structure["framing"] in {"wide", "full", "medium", "medium_close_up"}
			or (closing and structure["framing"] == "close_up")
		)
	)
	interaction = bool(
		contract.get("events")
		or any(r.get("kind") in {"contacts", "flows_from"} for r in contract.get("relations") or [])
	)
	framing = "the supplied opening composition"
	if structure:
		framing = framing_text(structure)
		if structure["subject_motion"] == "manipulation" and not broad_presentation:
			return {
				"version": 3,
				"behavior": "locked",
				"framing": framing,
				"direction": "The camera holds its supplied position, focal length and focus throughout the handling action. No pan, tilt, orbit, zoom or rack focus. "
				+ visibility_instruction(structure, contract),
				"reason": "Structured manipulation prioritizes readable contact and object-state changes.",
				"product_focus": product,
				"closing": closing,
			}
	views = shot.get("views_json") or []
	if isinstance(views, str):
		views = json.loads(views)
	if (
		structure
		and structure["subject_motion"] == "locomotion"
		and plan.get("camera_motion") != "locked"
		and not views
		and not plan.get("camera_intent")
	):
		return {
			"version": 3,
			"behavior": "tracking",
			"framing": framing,
			"direction": "The camera tracks smoothly with the moving subject at its real-time pace, preserving the supplied viewpoint, "
			"working distance and opening framing. Keep the subject size stable and required body parts inside the frame. "
			"Keep apparent subject height within five percent of its opening size throughout, including during hand actions; no pullback-and-return or change in focal length. "
			"No zoom, orbit, lateral drift or slow motion; camera speed follows the subject without delaying its action. "
			"The environment is one stationary three-dimensional location: persistent landmarks keep their identity and perspective changes follow continuous depth-dependent parallax. Never slide, loop, reset or replace a flat background independently of the camera.",
			"reason": "Structured locomotion uses one tracking behavior; framing comes from the approved opening.",
			"product_focus": product,
			"closing": closing,
		}
	if intent and plan.get("camera_motion") != "locked" and not views:
		behavior = intent["behavior"]
		if behavior in {"arc", "pull_back"}:
			endpoints = {str(r.get("reference_role") or r.get("input_role") or "").lower() for r in refs}
			if not intent["allow_reframe"] or not {"first_frame", "last_frame"} <= endpoints:
				return {
					"version": 4,
					"behavior": "locked",
					"framing": framing,
					"direction": "The camera holds its approved opening composition; no unanchored reveal, orbit or zoom.",
					"reason": "A spatial reveal needs both reviewed boundary images.",
					"product_focus": product,
					"closing": closing,
				}
		anchored_push = (
			behavior == "push_in" and broad_presentation and {"first_frame", "last_frame"} <= roles
		)
		if (
			behavior == "locked"
			or intent["allow_reframe"]
			or anchored_push
			or allows_push(framing_safety)
			or (generated_composition and broad_presentation and behavior == "push_in")
		):
			directions = {
				"locked": "The camera holds one static shot with fixed position, focal length and focus throughout; no pan, tilt, orbit, zoom or rack focus.",
				"tracking_backward": "The camera tracks backward smoothly at the moving subject's real-time pace, maintaining its screen size and the approved opening framing. Camera speed does not slow the action. The stationary setting has continuous depth-dependent parallax; no sliding or resetting backdrop. No orbit, zoom or lateral drift; settle at the ending composition.",
				"push_in": "The camera makes one smooth controlled push-in along the same optical axis toward the authored focal subject, following the supplied opening and ending compositions. No simultaneous pan, tilt, orbit or focus pull. Settle into the final view before the end.",
				"pull_back": "The camera makes one smooth axial dolly backward from the supplied opening to the reviewed wider ending, revealing the same three-dimensional setting. Preserve screen direction, subject scale progression and depth-dependent parallax; no orbit, pan or zoom pulse.",
				"arc": "The camera follows one smooth shallow arc of at most 12 degrees between the supplied reviewed viewpoints, keeping subject distance and screen size stable. The setting remains stationary with depth-dependent parallax. No simultaneous zoom, tilt or axis crossing.",
			}
			if behavior == "push_in" and not intent["allow_reframe"] and not anchored_push:
				limit = 6 if broad_presentation and intent.get("energy") in {"measured", "brisk"} else 2
				duration = float(shot.get("duration_seconds") or 5)
				settle = (
					max(0, duration - 2)
					if closing
					else duration * (0.5 if intent.get("energy") == "brisk" else 0.8)
				)
				directions["push_in"] = (
					f"The camera makes one smooth centred axial dolly-in, increasing apparent subject size by at most {limit} percent in total. "
					f"Ease in, travel with a {intent.get('energy', 'slow')} rhythm, and ease to a complete stop by {settle:g} seconds; hold the final composition through the end. "
					"Keep every required edge and contact inside the frame. The room is stationary; near and far landmarks show continuous depth-dependent parallax. No lateral drift, tilt, orbit, digital zoom pulse or focus pull."
				)
			return {
				"version": 2,
				"behavior": behavior,
				"framing": framing,
				"direction": directions[behavior],
				"reason": "Structured camera intent in the approved plan; never parsed from storyboard prose.",
				"product_focus": product,
				"closing": closing,
			}
	constrained = (
		plan.get("camera_motion") == "locked"
		or bool(views)
		or closing
		or (product and (interaction or (actor and position > 0)))
	)
	locked = constrained or not allows_push(framing_safety)
	if locked:
		behavior = "locked"
		direction = "The camera holds one static shot throughout, with fixed position, focal length and focus; no pan, tilt, zoom or rack focus."
		reason = (
			"Explicit preservation, split-screen, product interaction, or closing hold."
			if constrained
			else "Opening-frame subject margins are tight, cropped, or unverified."
		)
	else:
		behavior = "push_in"
		direction = "The camera makes one very slow, centred push-in over the first four fifths of the shot, increasing apparent subject size by at most 2 percent in total, then holds the final composition. Keep every visible subject edge and required component inside the frame throughout. No lateral drift, orbit, tilt, zoom pulse or focus change."
		reason = "Assessed complete subjects have at least eight percent margin on every side."
	return {
		"version": 2,
		"behavior": behavior,
		"framing": framing,
		"direction": direction,
		"reason": reason,
		"product_focus": product,
		"closing": closing,
	}


def without_camera(text):
	# Preserve exact dialogue, including camera words inside speech.
	quoted = []

	def stash(match):
		quoted.append(match.group())
		return f"__DIALOGUE_{len(quoted) - 1}__"

	text = re.sub(r'<d>.*?</d>|"[^"\n]*"|“[^”\n]*”', stash, str(text), flags=re.S)
	text = re.sub(r"\bCamera:\s*[^\n]*", "", text, flags=re.I)

	def keep_action(match):
		clause = re.search(r"\b(?:as|while)\s+(.+)", match.group(), re.I)
		return (" " + clause.group(1)) if clause else ""

	text = re.sub(
		r"(?:^|(?<=[.!?])\s+)(?:The camera\b|Camera\b|NO (?:camera|zoom|dolly|pan|rack focus)\b)[^.!?]*[.!?]?",
		keep_action,
		text,
		flags=re.I,
	)
	text = re.sub(r",?\s+(?:as|while|and) the camera\b[^.!?]*", "", text, flags=re.I)
	text = re.sub(
		r"(?:^|(?<=[.!?])\s+)(?:A single locked-off\b|EXACTLY the same camera\b|This is the last shot of the film:[^.!?]*\bcamera\b)[^.!?]*[.!?]?",
		"",
		text,
		flags=re.I,
	)
	text = re.sub(
		r"(?:^|(?<=[.!?])\s+)(?:(?:A|One)\s+)?(?:(?:barely|perceptible|very|slow|short|gentle|controlled|locked|static)\s+)*(?:dolly[- ]?in|push[- ]in|pull[- ]out|tracking shot|truck(?:s|ing)?|zoom|pan|tilt|orbit|rack focus)\b[^.!?]*[.!?]?",
		"",
		text,
		flags=re.I,
	)
	for i, value in enumerate(quoted):
		text = text.replace(f"__DIALOGUE_{i}__", value)
	return text.strip()
