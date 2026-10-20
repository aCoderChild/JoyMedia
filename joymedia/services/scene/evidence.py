"""Bounded, model-neutral temporal evidence checks.

Inspired by VideoPhy-2's separate action/physics/rule judgments and VBench's
separate consistency dimensions. This is an independent implementation, not
those benchmarks or their checkpoints. Sampled support is never brand approval.
"""

import hashlib
import json
import math
from dataclasses import dataclass

from joymedia.services.scene.contract import RELATIONS, proportion_claims, read_contract
from joymedia.services.scene.structure import structure_claims
from joymedia.services.scene.vendor.videophy2 import PROMPT_RULE

MAX_SAMPLES = 16
MAX_CLAIMS = 24
VERDICTS = {"supported", "violated", "uncertain"}


@dataclass
class SequenceCheck:
	pictures: list
	metadata: list
	claims: list
	context: dict


def sample_times(duration, fps, plan=None, frame_count=None):
	"""Uniform anchors plus event interiors and boundaries, at actual frame times."""
	if not all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in (duration, fps)):
		raise ValueError("Video duration and frame rate must be finite positive numbers.")
	if frame_count is not None and (type(frame_count) is not int or frame_count < 1):
		raise ValueError("Decoded frame count must be a positive integer.")
	# Container durations are commonly rounded to microseconds. Prefer the
	# actual stream count; rounding 124/24 must never request frame 124.
	last = frame_count - 1 if frame_count is not None else max(0, math.ceil(duration * fps - 1e-3) - 1)
	contract = read_contract(plan, duration)
	anchors = {round(last * i / 4) for i in range(5)}
	required = {0, last}
	for transition in (contract or {}).get("transitions", []):
		event = next(row for row in contract["events"] if row["id"] == transition["event"])
		indices = [
			min(last, max(0, round(moment * fps)))
			for moment in (event["start"], (event["start"] + event["end"]) / 2, event["end"])
		]
		if len(set(indices)) < 3:
			raise ValueError("A physical transition requires at least three distinct visible frames.")
		required.update(indices)
	if len(required) > MAX_SAMPLES:
		raise ValueError("Physical transitions exceed the sample budget; split this interaction.")
	anchors.update(required)
	if len(anchors) > MAX_SAMPLES:
		anchors = required
	candidates = set()
	for event in (contract or {}).get("events", []):
		for moment in (event["start"], (event["start"] + event["end"]) / 2, event["end"]):
			index = min(last, max(0, round(moment * fps)))
			candidates.update((max(0, index - 1), index, min(last, index + 1)))
	# Evenly distribute the remaining budget across event candidates; retain anchors.
	candidates = sorted(candidates - anchors)
	budget = MAX_SAMPLES - len(anchors)
	if budget == 0:
		candidates = []
	elif budget == 1:
		candidates = candidates[len(candidates) // 2 : len(candidates) // 2 + 1]
	elif len(candidates) > budget:
		candidates = [candidates[round(i * (len(candidates) - 1) / (budget - 1))] for i in range(budget)]
	return [index / fps for index in sorted(anchors | set(candidates))]


def claims_for(plan, duration, action):
	contract = read_contract(plan, duration)
	claims = [
		{
			"id": "action",
			"dimension": "action",
			"mode": "occurrence",
			"claim": str(action or "Show the authored scene action")[:2400],
		},
		{
			"id": "continuity",
			"dimension": "consistency",
			"claim": "Visible objects and body parts keep plausible continuity, ownership and contact across the sampled frames; nothing appears, disappears, duplicates or penetrates another solid without a visible explanation.",
		},
		{
			"id": "physics",
			"dimension": "physics",
			"claim": "Visible motion, gravity, material origins and object contacts are physically plausible for this scene's intended style.",
		},
	]
	if not contract:
		return claims
	labels = {row["id"]: row["label"] for row in contract["entities"]}
	for index, row in enumerate(contract["relations"]):
		claims.append(
			{
				"id": f"relation.{index}",
				"dimension": "physics",
				"mode": "occurrence" if row["kind"] in {"flows_from", "contacts"} else "invariant",
				"claim": f"{labels[row['subject']]} {RELATIONS[row['kind']]} {labels[row['object']]}",
			}
		)
	for index, claim in enumerate(proportion_claims(contract)):
		claims.append(
			{"id": f"proportion.{index}", "dimension": "staging", "mode": "invariant", "claim": claim}
		)
	for index, claim in enumerate(structure_claims(contract)):
		claims.append(
			{"id": f"structure.{index}", "dimension": "staging", "mode": "invariant", "claim": claim}
		)
	for row in contract.get("checks", []):
		claim = {
			"id": f"check.{row['id']}",
			"dimension": "staging",
			"mode": "invariant",
			"claim": row["claim"],
		}
		if row["scope"] == "opening":
			claim["window"] = [0, 0]
		elif row["scope"] == "event":
			event = next(e for e in contract["events"] if e["id"] == row["event"])
			claim.update(window=[event["start"], event["end"]], strict_window=True)
		claims.append(claim)
	for row in contract["events"]:
		claims.append(
			{
				"id": f"event.{row['id']}",
				"dimension": "action",
				"mode": "occurrence",
				"claim": row["description"],
				"window": [row["start"], row["end"]],
			}
		)
		for cause in row["after"]:
			earlier = next(e for e in contract["events"] if e["id"] == cause)
			claims.append(
				{
					"id": f"order.{cause}.{row['id']}",
					"dimension": "order",
					"mode": "occurrence",
					"claim": earlier["description"] + " happens BEFORE " + row["description"],
				}
			)
	for row in contract.get("transitions", []):
		event = next(event for event in contract["events"] if event["id"] == row["event"])
		claims.append(
			{
				"id": f"transition.{row['event']}",
				"dimension": "physics",
				"mode": "occurrence",
				"evidence_kind": "transition",
				"window": [event["start"], event["end"]],
				"claim": f"Before: {row['before']}. During: {row['during']}. After: {row['after']}. Contradiction: {row['forbidden']}",
			}
		)
	if len(claims) > MAX_CLAIMS:
		# Never silently drop the end of an authored contract to fit a model budget.
		raise ValueError(
			"Temporal review exceeds the bounded claim budget; split the interaction into shorter scenes."
		)
	return claims


def question(check):
	# Reuse VideoPhy-2's MIT-licensed physical-rule question, without its video
	# token/chat wrapper or checkpoint-specific numeric response protocol.
	rule_question = PROMPT_RULE.split("Human: ", 2)[2].split("\nChoose", 1)[0]
	rules = " ".join(
		rule_question.format(rule=row["claim"]) for row in check.claims if row["dimension"] == "physics"
	)
	phase_example = (
		',"phase_frames":{"before":0,"during":1,"after":2}'
		if any(row.get("evidence_kind") == "transition" for row in check.claims)
		else ""
	)
	frames_example = "[0,1,2]" if phase_example else "[0,1]"
	return (
		"Review this chronological sequence of sampled video frames. Each image is preceded by its zero-based frame ID and timestamp. "
		"Evaluate each claim independently. First observe the visible objects, then the interaction and event order. "
		"Use supported only when visible evidence establishes the claim; violated when visible evidence contradicts it; "
		"uncertain when occluded, between samples, too small, or ambiguous. Do not infer a correct action from the prompt. "
		"An object leaving the camera view is not disappearance. Printed characters are not extra actors. "
		"Every supported or violated verdict must cite a nonempty frames list using supplied frame IDs. "
		"For an unchanged invariant, cite the compared frames and describe the actual visible support, contact or continuity. "
		"An empty frames list means uncertain; 'no visible motion' alone cannot establish physical plausibility. "
		"A still or attractive picture does not establish motion. For order claims, supported needs at least two distinct chronological frames showing cause then effect. "
		"An interacting object is not automatically the material source. Distinguish stylized appearance from broken contact or causality. "
		"For evidence_kind=transition, inspect initial state, actual contact/motion and resulting material state independently. "
		"A touch or tool lift alone cannot prove the requested change. Compare the same region accounting for camera motion and occlusion. "
		"For a transition, supported requires three distinct chronological samples and phase_frames:{before:frame ID,during:frame ID,after:frame ID}. "
		"Every cited phase frame must also appear in frames. Explain the actual visible change, not the requested one. "
		"A hidden result, unchanged affected region or unexplained disappearance must not pass. Do not infer material transfer from an instruction or the tool's appearance. "
		"Do not certify product text, logos or fine character identity. Frame IDs must refer to these actual samples. "
		'Use compact JSON without indentation or repeated whitespace; reasons must be under 25 words. Return only JSON: {"observations":[{"id":"claim ID","verdict":"supported|violated|uncertain","frames":'
		+ frames_example
		+ ',"reason":"specific visible evidence"'
		+ phase_example
		+ "}]}. "
		"Return exactly one observation for every claim. Claims: "
		+ json.dumps(check.claims, ensure_ascii=False)
		+ " Physical-rule questions: "
		+ rules
	)


def evaluate(check, answer):
	"""Reject missing, duplicated, invented, mistyped or ungrounded machine evidence."""
	rows = answer.get("observations") if isinstance(answer, dict) else None
	if not isinstance(rows, list) or len(rows) > MAX_CLAIMS:
		rows = []
	results = []
	known = {claim["id"] for claim in check.claims}
	protocol_error = any(
		not isinstance(row, dict) or not isinstance(row.get("id"), str) or row.get("id") not in known
		for row in rows
	)
	for claim in check.claims:
		matches = [row for row in rows if isinstance(row, dict) and row.get("id") == claim["id"]]
		row = matches[0] if len(matches) == 1 else {}
		verdict, frames, reason = row.get("verdict"), row.get("frames"), row.get("reason")
		valid = (
			(verdict in VERDICTS if isinstance(verdict, str) else False)
			and isinstance(frames, list)
			and all(
				type(index) is int
				and 0 <= index < len(check.metadata)
				and index in check.context.get("allowed_indices", range(len(check.metadata)))
				for index in frames
			)
			and len(frames) == len(set(frames))
			and isinstance(reason, str)
			and bool(reason.strip())
		)
		if valid and verdict in {"supported", "violated"}:
			valid = bool(frames)
		if valid and verdict == "supported" and claim["dimension"] == "order":
			valid = len(frames) >= 2 and frames == sorted(frames)
		phases = row.get("phase_frames")
		if valid and verdict == "supported" and claim.get("evidence_kind") == "transition":
			valid = isinstance(phases, dict) and set(phases) == {"before", "during", "after"}
			if valid:
				ordered = [phases[key] for key in ("before", "during", "after")]
				valid = (
					all(type(index) is int and index in frames for index in ordered)
					and ordered[0] < ordered[1] < ordered[2]
				)
				start, end = claim["window"]
				expected = [
					min(range(len(check.metadata)), key=lambda i: abs(check.metadata[i]["time"] - time))
					for time in (start, (start + end) / 2, end)
				]
				valid = valid and ordered == expected
		if valid and claim.get("strict_window"):
			start, end = claim["window"]
			valid = all(start <= check.metadata[index]["time"] <= end for index in frames)
		if not valid or protocol_error:
			verdict, reason = "uncertain", "Missing, malformed or ungrounded temporal evidence."
			frames = []
		result = {**claim, "verdict": verdict, "frames": frames, "reason": str(reason)[:500]}
		if valid and verdict == "supported" and claim.get("evidence_kind") == "transition":
			result["phase_frames"] = phases
		if verdict == "supported" and "window" in claim:
			start, end = claim["window"]
			result["timing_alignment"] = (
				"within authored window"
				if any(start <= check.metadata[index]["time"] <= end for index in frames)
				else "observed outside authored window"
			)
		results.append(result)
	scope = (
		"scene"
		if check.context.get("required_claim_ids") == [row["id"] for row in check.claims]
		else "partial"
	)
	opening = check.context.get("opening_state")
	if scope == "scene" and opening:
		results.insert(
			0,
			{
				"id": "opening.condition",
				"dimension": "consistency",
				"claim": "The video starts from its frozen conditioning image.",
				**opening,
			},
		)
	return {
		"version": 1,
		**check.context,
		"scope": scope,
		"samples": check.metadata,
		"results": results,
		"status": "Passed"
		if results and all(row["verdict"] == "supported" for row in results)
		else "Needs Review",
		"limitations": "Sampled machine evidence only; does not certify unsampled motion, fine identity, packaging or logos.",
	}


def digest(data):
	return hashlib.sha256(data).hexdigest()


def batches(check):
	"""Small requests work with deployed low-context vision runtimes as well as larger ones.

	Keep chronological windows for continuity; target authored windows for events.
	Each request contains at most four images and one claim.
	"""
	groups = {}
	for claim in check.claims:
		if claim.get("evidence_kind") == "transition":
			start, end = claim["window"]
			indices = tuple(
				sorted(
					{
						min(range(len(check.metadata)), key=lambda i: abs(check.metadata[i]["time"] - time))
						for time in (start, (start + end) / 2, end)
					}
				)
			)
			if len(indices) < 3:
				raise ValueError(
					"Physical transition evidence requires distinct before/contact/after samples."
				)
			windows = [indices]
		elif claim.get("window") == [0, 0]:
			windows = [(0,)]
		elif claim["id"] == "action":
			windows = [tuple(sorted({round(i * (len(check.metadata) - 1) / 3) for i in range(4)}))]
		elif "window" in claim:
			start, end = claim["window"]
			indices = [i for i, row in enumerate(check.metadata) if start <= row["time"] <= end]
			if not indices:
				if claim.get("strict_window"):
					raise ValueError("No sampled frame falls inside the required action-phase check.")
				indices = [
					min(
						range(len(check.metadata)),
						key=lambda i: abs(check.metadata[i]["time"] - (start + end) / 2),
					)
				]
			if len(indices) > 4:
				indices = [indices[round(i * (len(indices) - 1) / 3)] for i in range(4)]
			windows = [tuple(indices)]
			# Retrieve delayed events elsewhere too; authored timing is a sampling
			# hint, not proof that the event is absent from the actual clip.
			if not claim.get("strict_window"):
				windows += [
					tuple(range(start, min(start + 4, len(check.metadata))))
					for start in range(0, len(check.metadata), 3)
				]
		elif claim["dimension"] == "order":
			_, cause, effect = claim["id"].split(".")
			events = {
				row["id"].removeprefix("event."): row
				for row in check.claims
				if row["id"].startswith("event.")
			}
			times = [t for key in [cause, effect] for t in events[key]["window"]]
			windows = [
				tuple(
					sorted(
						{
							min(range(len(check.metadata)), key=lambda i: abs(check.metadata[i]["time"] - t))
							for t in times
						}
					)
				),
				tuple(sorted({round(i * (len(check.metadata) - 1) / 3) for i in range(4)})),
			]
		else:
			windows = [
				tuple(range(start, min(start + 4, len(check.metadata))))
				for start in range(0, len(check.metadata), 3)
			]
		# Keep full chronological coverage without asking again about a trailing
		# singleton already present in a larger window of this same claim.
		windows = list(dict.fromkeys(windows))
		windows = [w for w in windows if not any(set(w) < set(other) for other in windows)]
		for indices in windows:
			groups.setdefault(indices, []).append(claim)
	for indices, claims in groups.items():
		for start in range(0, len(claims)):
			yield indices, claims[start : start + 1]


def merge_observations(check, reports):
	"""Violations dominate. Occurrences need a witness; invariants need every window.

	Absence before an event is not evidence against its later occurrence. Raw
	window verdicts are retained in the report, including all uncertainty.
	"""
	observations = []
	for claim in check.claims:
		rows = [row for report in reports for row in report["results"] if row["id"] == claim["id"]]
		bad = [row for row in rows if row["verdict"] == "violated"]
		unclear = [row for row in rows if row["verdict"] == "uncertain"]
		witnesses = (
			[row for row in rows if row["verdict"] == "supported"]
			if claim.get("mode") == "occurrence"
			else []
		)
		selected = bad or witnesses or unclear or rows
		observations.append(
			{
				"id": claim["id"],
				"verdict": "violated"
				if bad
				else "supported"
				if witnesses
				else "uncertain"
				if unclear or not rows
				else "supported",
				"frames": sorted({index for row in selected for index in row["frames"]}),
				"reason": "; ".join(dict.fromkeys(row["reason"] for row in selected))[:500]
				or "No temporal evidence returned.",
				**(
					{"phase_frames": witnesses[0]["phase_frames"]}
					if witnesses and "phase_frames" in witnesses[0] and not bad
					else {}
				),
			}
		)
	return evaluate(check, {"observations": observations})


def compare_opening(reference_bytes, frame_bytes):
	"""Independent image-condition check; differences request review, never a GPU redo.

	Blurring/downsampling tolerates normal codec and VAE texture differences.
	Global and local errors catch substantial state changes hidden by a static
	background. These are explicit image tolerances, not physics probabilities.
	"""
	import io

	from PIL import Image, ImageChops, ImageFilter, ImageStat

	with Image.open(io.BytesIO(reference_bytes)) as source, Image.open(io.BytesIO(frame_bytes)) as first:
		if abs(source.width / source.height - first.width / first.height) > 0.02:
			return {
				"verdict": "uncertain",
				"frames": [0],
				"reason": "The conditioning and output aspect ratios differ; review the authored crop.",
			}
		size = (144, 256) if first.height >= first.width else (256, 144)
		images = [
			image.convert("RGB").resize(size, Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(1))
			for image in [source, first]
		]
	difference = ImageChops.difference(*images)
	mean = sum(ImageStat.Stat(difference).mean) / (3 * 255)
	width, height = size
	tiles = [
		sum(ImageStat.Stat(difference.crop((x, y, x + width // 8, y + height // 8))).mean) / (3 * 255)
		for y in range(0, height, height // 8)
		for x in range(0, width, width // 8)
	]
	changed = mean > 0.06 or max(tiles) > 0.15
	return {
		"verdict": "violated" if changed else "supported",
		"frames": [0],
		"reason": "The opening differs substantially from the frozen conditioning image; review continuity."
		if changed
		else "The opening is within the configured global and local image-difference tolerances.",
		"mean_error": mean,
		"max_tile_error": max(tiles),
		"mean_tolerance": 0.06,
		"tile_tolerance": 0.15,
		"reference_sha256": digest(reference_bytes),
		"opening_sha256": digest(frame_bytes),
	}
