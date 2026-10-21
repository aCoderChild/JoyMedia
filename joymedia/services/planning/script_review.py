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
				"narrative_stage",
				"subject_motion",
			)
		}
		for scene in script["scenes"]
	]
	prompt = (
		"First check the creative_direction in REQUIREMENTS. Report explicit contradictions as brief_contradiction, quoting the contradictory scene text and the required correction. "
		"Check the causal sequence of the complete screenplay, across ALL scenes in order. "
		"Different shots perform different jobs: acquisition need not also demonstrate use; a later use shot can show contact and its result. "
		"Do not request the same demonstration in every scene. A stated press/wipe against a spill is contact; a stated wet material or reduced liquid is a result. "
		"Report a defect only when the screenplay actually contradicts prerequisites or omits a necessary action throughout the whole sequence. "
		"For coverage copy one exact action substring from each scene, without paraphrasing. "
		"Use production_detail for additional mechanical/staging specificity that expands an otherwise valid action. These notes go to the normal production planner. Reserve missing_contact_or_result for an actually absent demonstration/result or an effect contradicting stated contact; do not confuse high-level script wording with a rendered failure. "
		"Report only actionable TEXT defects, each with an EXACT substring demonstrating that defect and a precise rewrite instruction. A merely related action is not evidence of a defect. Request concrete revised action/staging text, not generic review, ensure or clarify instructions. An empty issues list is valid. "
		"An action changing an object/state is progress, even if a brief reaction accompanies it. Do not invent problems in a valid action. "
		"Check: only roster actors in prose; items obtained before use; holding a container does not obtain its contents; contact precedes the visible result; no unexplained state reset or reversal of consumption; opening and action agree. "
		"Check product construction against reference descriptions: no invented rigid lids or closure mechanisms. Returning used consumable material to unused stock is a state_reset, not a valid way to reset a demonstration. "
		"Name each interaction target before use; an unspecified target is not a concrete demonstration. Never replace an existing tangible action with an invented unrelated prop. "
		"A scene spent solely approaching, staring or posing lacks brisk action. Camera commands belong outside Action, even at the end. Only the final scene may hold the product briefly. "
		"For idle_pacing, looking/inspecting followed only by nodding or smiling is still a reaction-only scene. Flag repeated product-presentation holds across consecutive scenes; move that runtime to distinct tangible product interactions without adding unsupported capabilities. "
		"Use purposeful shot-size/angle contrast and a product detail at use, with coherent axis and state handoffs. Do not demand an object reset unless a later opening explicitly contradicts its retained state. Historical feedback describes earlier renders, not defects proven in this draft. Never copy historical scene numbers, review/sign-off requests or old judgments into new issues. "
		"Use coverage for contradictory narrative_stage labels: establish is introductory geography, extract is contents removal, detail is contact/function, inspect is result examination and hero is final branded presentation. Do not label every shot establish. "
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
			return _cross_check_missing_actions(result, script)
		except (ValueError, KeyError, TypeError) as exc:
			repair = f"\nReview protocol repair {attempt + 1}: {exc} Return the full review, copying exact source text."
	raise ValueError("Script review could not provide grounded scene evidence: " + repair)


def _cross_check_missing_actions(review, script):
	"""Cross-check omission and pacing findings against authored action text.

	An exact quotation is needed to retract a claimed omission. This checks text
	coverage, never whether future generated pixels satisfy that text.
	"""
	from joymedia.services.planning.production import _ask_planner

	actions = [scene["action"] for scene in script["scenes"]]
	for finding in review["issues"]:
		if finding["category"] not in {"missing_contact_or_result", "missing_prerequisite", "idle_pacing"}:
			continue
		idle = finding["category"] == "idle_pacing"
		question = (
			"Check an idle_pacing finding against ONLY the quoted scene's full action. "
			"A visible change of material form, object location or contact is tangible progress, even with a brief reaction. "
			"The final branded presentation may hold briefly; it need not introduce another product use. "
			"Copy an exact action substring FROM THIS SCENE demonstrating such progress or the allowed final presentation. "
			"Return an empty string if the scene is only idle posing/looking. Do not invent an unrelated prop or demand an additional use.\n"
			+ json.dumps(
				{
					"scene": finding["scene"],
					"is_final": finding["scene"] == len(actions),
					"action": actions[finding["scene"] - 1],
				}
			)
			if idle
			else "Check one alleged omission against the COMPLETE ordered action sequence. "
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
			+ json.dumps(actions, ensure_ascii=False),
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
			raise ValueError("Omission cross-check requires quoted screenplay text.")
		if not quote.strip():
			continue
		normalized = " ".join(quote.split()).casefold()
		allowed_actions = [actions[finding["scene"] - 1]] if idle else actions
		if not any(normalized in " ".join(action.split()).casefold() for action in allowed_actions):
			raise ValueError("Omission cross-check quoted text absent from the action sequence.")
		finding["text_cross_check"] = {"already_written": quote, "physical_qualification": False}
		finding["category"] = "production_detail"
	return review
