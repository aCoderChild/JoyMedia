"""Quoted script compliance findings; independent of rendered-media admission."""

import json


def review_script_actions(script, roster=(), review_notes=(), requirements=None):
	"""Ground script revisions in exact text; this never reviews future pixels."""
	from joymedia.services.planning.production import _ask_planner

	count = len(script["scenes"])

	def obj(properties):
		return {
			"type": "object",
			"properties": properties,
			"required": list(properties),
			"additionalProperties": False,
		}

	index = {"type": "integer", "minimum": 1, "maximum": count}
	quote = {"type": "string", "minLength": 1, "maxLength": 200}
	issue = obj(
		{
			"scene": index,
			"category": {
				"type": "string",
				"enum": [
					"unreferenced_actor",
					"missing_prerequisite",
					"missing_contact_or_result",
					"production_detail",
					"state_reset",
					"opening_mismatch",
					"idle_pacing",
					"camera_in_action",
					"coverage",
					"brief_contradiction",
				],
			},
			"quote": quote,
			"instruction": {"type": "string", "minLength": 1, "maxLength": 280},
		}
	)
	schema = obj(
		{
			"coverage": {
				"type": "array",
				"items": obj({"scene": index, "action_quote": quote}),
				"minItems": count,
				"maxItems": count,
			},
			"issues": {"type": "array", "items": issue, "maxItems": 8},
		}
	)
	draft = [
		{
			k: scene.get(k, "")
			for k in (
				"duration_seconds",
				"visual_camera",
				"action",
				"visible_change",
				"continuity_rules",
				"cast",
				"products",
				"shot_framing",
				"shot_angle",
				"subject_motion",
				"voice_over",
				"on_screen_text",
			)
		}
		for scene in script["scenes"]
	]
	prompt = (
		"First check the creative_direction in REQUIREMENTS. Report explicit contradictions as brief_contradiction, quoting the contradictory scene text and the required correction. "
		"Check the causal sequence of the complete screenplay, across ALL scenes in order. "
		"A prerequisite written in a later scene cannot justify an earlier use. Compare voice_over and on_screen_text to what the visible action demonstrates; report a concrete contradiction as brief_contradiction, without treating an ordinary brand statement as an action claim. "
		"Different shots perform different jobs: acquisition need not also demonstrate use; a later use shot can show contact and its result. "
		"Do not request the same demonstration in every scene. A stated press/wipe against a spill is contact; a stated wet material or reduced liquid is a result. "
		"Report a defect only when the screenplay actually contradicts prerequisites or omits a necessary action throughout the whole sequence. "
		"For coverage copy one exact action substring from each scene, without paraphrasing. "
		"Use production_detail for additional mechanical/staging specificity that expands an otherwise valid action. These notes go to the normal production planner. Reserve missing_contact_or_result for an actually absent demonstration/result or an effect contradicting stated contact; do not confuse high-level script wording with a rendered failure. "
		"Report only actionable TEXT defects, each with an EXACT substring demonstrating that defect and a precise rewrite instruction. A merely related action is not evidence of a defect. Request concrete revised action/staging text, not generic review, ensure or clarify instructions. An empty issues list is valid. "
		"An action changing an object/state is progress, even if a brief reaction accompanies it. Do not invent problems in a valid action. "
		"Use opening_mismatch only for a stated opening object/pose state that conflicts with the first action; cite both incompatible states in the rewrite instruction. A suggestion to face a product differently or hold it longer is not such a contradiction. Never lengthen idle presentation to fix pacing. "
		"Check: only roster actors in prose; items obtained before use; holding a container does not obtain its contents; contact precedes the visible result; no unexplained state reset or reversal of consumption; opening and action agree. "
		"Audit reach and object occupancy across consecutive shots. If an actor is seated away from a table, do not accept a reach to objects on that table without a visible change of position or a reachable staging description. Count occupied hands or paws: an actor cannot simultaneously hold more separate props than available hands or paws, and must visibly set down or transfer an object before grasping another. Flag these as missing_prerequisite with the exact action quote and a concrete staging or transfer correction. Check that an object does not change support surface or location between shots without an explicit move. A product interaction must have a plausible contact path and support, not pass through a table or actor body. "
		"Check product construction against reference descriptions: no invented rigid lids or closure mechanisms. Returning used consumable material to unused stock is a state_reset, not a valid way to reset a demonstration. "
		"Check any performance demonstration against approved_claims and its literal approved_claims_english translation in REQUIREMENTS. Do not reject a capability that either clearly approves; do not infer a stronger capability from a loose translation. Pouring liquid, removing stains or claiming strength/absorbency is a brief_contradiction only when the corresponding capability is absent; ordinary handling is allowed. Quote the demonstration and request a visible action within the supplied claims. "
		"Check action_reference_observations and mandatories in REQUIREMENTS. When action observations are empty, allow only a physical effect explicitly required by mandatories and supported by approved claims; its cause, contact and gradual visible result must be staged in order. Flag any other invented fluid, stain, stress or multi-object performance effect as brief_contradiction. Ordinary acquisition, extraction, placement, folding and wearing remain allowed without motion footage. "
		"Name each interaction target before use; an unspecified target is not a concrete demonstration. Never replace an existing tangible action with an invented unrelated prop. "
		"Cast and product declarations apply to ALL scene fields, including continuity, opening, ending and camera prose. A scene with empty cast cannot keep an actor in continuity or describe that actor sitting nearby. Flag that contradiction with its exact quote. Characters printed on packaging are flat artwork, not physical cast. "
		"A scene spent solely approaching, staring or posing lacks brisk action. Camera commands belong outside Action, even at the end. One near-ending product-detail view may hold readable original packaging before a distinct final CTA. "
		"For idle_pacing, looking/inspecting followed only by nodding or smiling is still a reaction-only scene. Flag repeated presentation holds only when adjacent scenes repeat the same framing and information; use the time for a new product detail or tangible interaction without adding unsupported capabilities. "
		"Use purposeful shot-size/angle contrast and a product detail at use, with coherent axis and state handoffs. Do not demand an object reset unless a later opening explicitly contradicts its retained state. Historical feedback describes earlier renders, not defects proven in this draft. Never copy historical scene numbers, review/sign-off requests or old judgments into new issues. "
		"When a multi-scene character commercial keeps the actor in the source pose for every opening despite authored actions needing different reach, support or orientation, report a coverage issue with an exact scene quote. Ask for one feasible, visible body-state transition and carry that state forward; do not demand gratuitous movement or an impossible pose. A new camera crop of the same seated body does not resolve this issue. "
		"Narrative stage labels are proposals recomputed by the production planner, so review visible actions, framing and continuity rather than rejecting a label. "
		"For subject_motion, whole-body travel is locomotion even while carrying an object. Handling in place is manipulation; no subject movement is stationary. Flag a contradictory label as coverage, quoting the authored movement. "
		"This is TEXT review, not video review. Do not claim an action is convincing/unconvincing, or physical correctness is proven. If text already specifies contact and visible result, do not repeat an old request to verify physical correctness. Missing contact/result text needs a specific proposed visible-state edit. "
		"Never reject a valid causal event merely for lacking emotional complexity.\nROSTER: "
		+ json.dumps(roster, ensure_ascii=False)
		+ "\nREQUIREMENTS: "
		+ json.dumps(requirements or {}, ensure_ascii=False)
		+ "\nCURRENT INPUT FEEDBACK (earlier-render findings are retained separately, not proof of a new text defect): "
		+ json.dumps([r for r in review_notes if r.get("scope") == "Current"], ensure_ascii=False)
		+ "\nDRAFT: "
		+ json.dumps(draft, ensure_ascii=False)
	)
	repair = ""
	for attempt in range(2):
		result = _ask_planner(
			prompt + repair,
			system="You edit commercial scripts using exact quoted text. Return only the required JSON. Enforce the primary creative direction before other stylistic checks.\nPRIMARY USER DIRECTION: "
			+ str((requirements or {}).get("creative_direction") or ""),
			capability="writer",
			sampling_profile="creative_script_review",
			response_schema=schema,
		)
		try:
			coverage, issues = result.get("coverage", []), result.get("issues", [])
			if (
				not isinstance(coverage, list)
				or len(coverage) != count
				or any(not isinstance(row, dict) or type(row.get("scene")) is not int for row in coverage)
				or [r.get("scene") for r in coverage] != list(range(1, count + 1))
			):
				raise ValueError("Review must cover each scene exactly once in order.")

			def contained(quote, text):
				return (
					isinstance(quote, str)
					and bool(quote.strip())
					and " ".join(quote.split()).casefold() in " ".join(text.split()).casefold()
				)

			for row in coverage:
				if not contained(row.get("action_quote"), script["scenes"][row["scene"] - 1]["action"]):
					raise ValueError("Copy an exact action substring; do not paraphrase coverage evidence.")
			if not isinstance(issues, list) or len(issues) > 8:
				raise ValueError("Return a bounded list of actionable issues.")
			for row in issues:
				if (
					not isinstance(row, dict)
					or row.get("category") not in issue["properties"]["category"]["enum"]
					or not isinstance(row.get("instruction"), str)
					or not row["instruction"].strip()
					or len(row["instruction"]) > 280
				):
					raise ValueError(
						"Every issue needs a supported category and concrete rewrite instruction."
					)
				if (
					type(row.get("scene")) is not int
					or not 1 <= row["scene"] <= count
					or not contained(
						row.get("quote"), "\n".join(str(value) for value in draft[row["scene"] - 1].values())
					)
				):
					raise ValueError("Every issue must quote the exact affected scene text.")
			return _cross_check_opening(
				_cross_check_missing_actions(
					_filter_allowed_product_presentation(
						_filter_unsubstantiated_camera_issues(result, script), script
					),
					script,
				),
				script,
			)
		except (ValueError, KeyError, TypeError) as exc:
			repair = f"\nReview protocol repair {attempt + 1}: {exc} Return the full review, copying exact source text."
	raise ValueError("Script review could not provide grounded scene evidence: " + repair)


def _filter_allowed_product_presentation(review, script):
	"""A brief closing product insert is an intentional ad beat, not idle pacing."""
	last = len(script["scenes"])
	kept = []
	for finding in review["issues"]:
		index = finding["scene"]
		scene = script["scenes"][index - 1]
		allowed = index == last or (
			index == last - 1 and scene.get("shot_framing") in {"close_up", "extreme_close_up"}
		)
		if (
			finding["category"] == "idle_pacing"
			and allowed
			and scene.get("products")
			and not scene.get("cast")
		):
			continue
		kept.append(finding)
	review["issues"] = kept
	return review


def _filter_unsubstantiated_camera_issues(review, script):
	"""A camera-in-action finding must actually quote camera prose from Action."""
	from joymedia.services.planning.camera import without_camera

	kept = []
	for finding in review["issues"]:
		if finding["category"] != "camera_in_action":
			kept.append(finding)
			continue
		quote = str(finding["quote"])
		action = str(script["scenes"][finding["scene"] - 1].get("action") or "")
		if quote.casefold() in action.casefold() and without_camera(quote).strip() != quote.strip():
			kept.append(finding)
	review["issues"] = kept
	return review


def _cross_check_missing_actions(review, script):
	"""Cross-check omission and pacing findings against authored action text.

	An exact quotation is needed to retract a claimed omission. This checks text
	coverage, never whether future generated pixels satisfy that text.
	"""
	from joymedia.services.planning.production import _ask_planner

	actions = [scene["action"] for scene in script["scenes"]]
	openings = [
		"\n".join(str(scene.get(key) or "") for key in ("visual_camera", "continuity_rules"))
		for scene in script["scenes"]
	]
	for finding in review["issues"]:
		if finding["category"] not in {"missing_contact_or_result", "missing_prerequisite", "idle_pacing"}:
			continue
		idle = finding["category"] == "idle_pacing"
		question = (
			"Check an idle_pacing finding against ONLY the quoted scene's full action. "
			"A visible change of material form, object location or contact is tangible progress, even with a brief reaction. "
			"A near-ending product-detail view or final branded presentation may hold briefly; it need not introduce another product use. "
			"Copy an exact action substring FROM THIS SCENE demonstrating such progress or the allowed final presentation. "
			"Return an empty string if the scene is only idle posing/looking. Do not invent an unrelated prop or demand an additional use.\n"
			+ json.dumps(
				{
					"scene": finding["scene"],
					"is_closing_detail": finding["scene"] >= len(actions) - 1,
					"action": actions[finding["scene"] - 1],
				}
			)
			if idle
			else "Check one alleged omission against the COMPLETE ordered action sequence. "
			"For a missing prerequisite, an explicitly staged opening position or support "
			"exists before that scene's first action; it can establish reach but cannot "
			"substitute for an acquisition, contact, transfer or visible result. "
			"Is the requested action/result already explicitly written, either in a later phase of the "
			"same shot or the appropriate earlier/later shot? Return an exact action substring that "
			"already satisfies it, or an empty string when absent or causally out of order. "
			"Do not add actions, infer unseen results, or judge future video quality.\n"
		)
		answer = _ask_planner(
			question
			+ "\nFINDING: "
			+ json.dumps(finding, ensure_ascii=False)
			+ "\nORDERED ACTIONS: "
			+ json.dumps(actions, ensure_ascii=False)
			+ "\nOPENING STATES: "
			+ json.dumps(openings, ensure_ascii=False),
			system="You check a quoted screenplay defect against written actions. Return JSON only; never qualify future pixels.",
			capability="writer",
			sampling_profile="creative_script_review",
			response_schema={
				"type": "object",
				"properties": {"already_written": {"type": "string", "maxLength": 400}},
				"required": ["already_written"],
				"additionalProperties": False,
			},
		)
		quote = answer.get("already_written") if isinstance(answer, dict) else None
		if not isinstance(quote, str):
			finding["cross_check_error"] = (
				"Retraction did not supply quoted screenplay text; original finding retained."
			)
			continue
		if not quote.strip():
			continue
		normalized = " ".join(quote.split()).casefold()
		allowed_actions = [actions[finding["scene"] - 1]] if idle else actions
		if finding["category"] == "missing_prerequisite":
			allowed_actions = [*allowed_actions, openings[finding["scene"] - 1]]
		if not any(normalized in " ".join(action.split()).casefold() for action in allowed_actions):
			finding["cross_check_error"] = (
				"Retraction quoted text absent from the applicable action sequence; original finding retained."
			)
			continue
		if finding["category"] == "missing_prerequisite":
			# Acquisition in a later shot is not evidence for an earlier use.
			# A same-shot prerequisite must precede the quoted dependent action.
			dependent = " ".join(str(finding.get("quote") or "").split()).casefold()
			scene_index = finding["scene"] - 1
			prior = any(normalized in " ".join(action.split()).casefold() for action in actions[:scene_index])
			current = " ".join(actions[scene_index].split()).casefold()
			opening = " ".join(openings[scene_index].split()).casefold()
			within = bool(dependent) and (
				(normalized in opening)
				or (
					normalized in current
					and dependent in current
					and current.index(normalized) + len(normalized) <= current.index(dependent)
				)
			)
			if not prior and not within:
				finding["cross_check_error"] = (
					"The quoted prerequisite does not precede the dependent action; original finding retained."
				)
				continue
		finding["text_cross_check"] = {"already_written": quote, "physical_qualification": False}
		finding["category"] = "production_detail"
	return review


def _cross_check_opening(review, script):
	"""Require an explicit incompatible opening and first action before blocking a draft."""
	from joymedia.services.planning.production import _ask_planner

	for finding in review["issues"]:
		if finding["category"] != "opening_mismatch":
			continue
		scene = script["scenes"][finding["scene"] - 1]
		opening = "\n".join(str(scene.get(key) or "") for key in ("visual_camera", "continuity_rules"))
		action = str(scene.get("action") or "")
		answer = _ask_planner(
			"Check ONLY whether the stated opening pose or object state logically conflicts with "
			"this scene's first visible action. Copy exact substrings from the opening and action. "
			"Walking closer may begin near a table; do not infer a contradiction from ordinary movement. "
			"If no opening state is actually written, opening_quote is empty and contradiction is false. "
			"Never assess future rendered pixels.\nOPENING: "
			+ opening
			+ "\nACTION: "
			+ action
			+ "\nFINDING: "
			+ json.dumps(finding, ensure_ascii=False),
			system="You verify an alleged screenplay contradiction using exact quoted text. Return JSON only.",
			capability="writer",
			sampling_profile="creative_script_review",
			response_schema={
				"type": "object",
				"properties": {
					"opening_quote": {"type": "string", "maxLength": 200},
					"action_quote": {"type": "string", "maxLength": 200},
					"contradiction": {"type": "boolean"},
				},
				"required": ["opening_quote", "action_quote", "contradiction"],
				"additionalProperties": False,
			},
		)
		if not isinstance(answer, dict) or type(answer.get("contradiction")) is not bool:
			finding["cross_check_error"] = (
				"Opening cross-check returned no usable verdict; original finding retained."
			)
			continue
		opening_quote, action_quote = answer.get("opening_quote"), answer.get("action_quote")
		if not isinstance(opening_quote, str) or not isinstance(action_quote, str):
			finding["cross_check_error"] = (
				"Opening cross-check omitted quoted text; original finding retained."
			)
			continue

		def contained(quote, source):
			return " ".join(quote.split()).casefold() in " ".join(source.split()).casefold()

		if (opening_quote.strip() and not contained(opening_quote, opening)) or (
			action_quote.strip() and not contained(action_quote, action)
		):
			finding["cross_check_error"] = (
				"Opening cross-check quoted absent text; original finding retained."
			)
			continue
		if answer["contradiction"]:
			if not opening_quote.strip() or not action_quote.strip():
				finding["cross_check_error"] = (
					"Opening contradiction lacks both exact states; original finding retained."
				)
			continue
			finding["opening_evidence"] = {"opening": opening_quote, "action": action_quote}
		else:
			finding["category"] = "production_detail"
			finding["text_cross_check"] = {
				"opening": opening_quote,
				"action": action_quote,
				"contradiction": False,
				"physical_qualification": False,
			}
	return review
