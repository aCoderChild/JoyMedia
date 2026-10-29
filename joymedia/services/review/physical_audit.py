"""Describe-then-compare audit of a drawn first frame (the PhyT2V method, CVPR 2025).

A yes/no checker finds only what it is asked about, and answers "unclear" for the
rest: a mascot cut by an armrest, drawn twice the size of its armchair, or redrawn
as a flat cartoon passes. Here the vision model first describes what is actually
drawn (what carries each figure, what its body overlaps, its size against that
furniture, extra people, product count, rendering medium) and code compares the
description with the scene: its cast, product placement, the sheet's "Logic / Liên tục"
rules and the reference medium. Findings use the "Critical ..." notes that the
automatic scene repair already reads. Product placement is assessed against the
visible environment, so this remains applicable to any support, object, or setting.
"""

import re

import frappe

OBVIOUS_GEOMETRY = {
	"solid_intersection": "Solid bodies do not visibly pass through or fuse with other solid bodies",
	"unsupported_load": "Stationary weight-bearing objects have visible plausible support or a visible grip",
	"implausible_scale": "Object scale is physically plausible against nearby objects at comparable depth",
}

SUPPORT_CLASSES = {
	"rug": "ground",
	"floor": "ground",
	"ground": "ground",
	"chair": "seat",
	"sofa": "seat",
	"seat": "seat",
	"bench": "seat",
	"table": "work_surface",
	"coffee table": "work_surface",
	"counter": "work_surface",
}


def opening_actor_support(opening):
	"""Extract only an explicit, unambiguous authored seated/standing support.

	Unrecognised prose stays unknown. This does not infer support from the
	location, furniture inventory, or a future action.
	"""
	mentions = re.findall(
		r"\b(?:seated|sitting|sits|standing|stands)\s+(?:directly\s+)?on\s+"
		r"(?:(?:a|an|the)\s+)?(?:(?:cozy|soft|thick|thin|small|large|low|wooden|padded|patterned)\s+){0,3}"
		r"(coffee table|rug|floor|ground|chair|sofa|seat|bench|table|counter)\b",
		str(opening or ""),
		re.I,
	)
	classes = {SUPPORT_CLASSES[s.casefold()] for s in mentions}
	return next(iter(classes)) if len(classes) == 1 else None


def obvious_geometry_results(pictures, *, opening="", configured=None, ask=None):
	"""Observe positive defects, then negate strict evidence in code.

	These checks also run on decoded video, after source-art compositing. An
	unknown observation cannot clear a frame; a witnessed defect cannot become
	an advisory pass. No dimensions or furniture topology are invented here.
	"""
	if ask is None:
		from joymedia.services.review.consistency import ask

	observations = []
	expected_support = opening_actor_support(opening)
	defect_schema = {
		"type": "object",
		"additionalProperties": False,
		"required": ["present", "evidence"],
		"properties": {
			"present": {"type": ["boolean", "null"]},
			"evidence": {"type": "string", "minLength": 1},
		},
	}
	schema = {
		"type": "object",
		"additionalProperties": False,
		"required": [*OBVIOUS_GEOMETRY, "actor_support"],
		"properties": {
			**{key: defect_schema for key in OBVIOUS_GEOMETRY},
			"actor_support": {
				"type": "object",
				"additionalProperties": False,
				"required": ["surface", "evidence"],
				"properties": {
					"surface": {
						"type": "string",
						"enum": [
							"ground",
							"seat",
							"work_surface",
							"product",
							"airborne",
							"hidden",
							"none",
							"multiple",
						],
					},
					"evidence": {"type": "string", "minLength": 1},
				},
			},
		},
	}
	for picture in pictures:
		question = (
			"Observe visible geometry and fill the required JSON fields from the image. "
			"solid_intersection means solid objects pass through or fuse with each other. "
			"unsupported_load means a stationary object visibly floats without support or a grip. "
			"implausible_scale means an object has clearly impossible scale relative to nearby objects. "
			"For each defect, present=true for a clear violation, false for visibly coherent geometry, "
			"null for hidden/ambiguous geometry; give concrete evidence. Ordinary occlusion is not "
			"solid intersection. Jumping/flying is not unsupported stationary weight. Compare scale "
			"only at comparable depth; miniature subjects are allowed. "
			"Describe what actually carries the foreground actor's weight: actor_support.surface is "
			"ground, seat, work_surface, product, airborne, hidden, none or multiple. "
			"Use none if no physical actor exists, multiple if actors have different supports. "
			"Printed characters are not physical actors. Do not guess hidden contact."
		)
		answer = ask(picture, question, configured=configured, max_edge=768, schema=schema)
		observations.append(answer if isinstance(answer, dict) else {})
	claims = dict(OBVIOUS_GEOMETRY)
	if expected_support:
		claims["wrong_opening_support"] = (
			"Visible starting support agrees with the authored opening: " + str(opening)[:1800]
		)
	results = []
	for key, claim in claims.items():
		rows = []
		for index, answer in enumerate(observations):
			if key == "wrong_opening_support" and index != 0:
				continue
			row = answer.get(key)
			if key == "wrong_opening_support":
				support = answer.get("actor_support") or {}
				support = support if isinstance(support, dict) else {}
				actual = support.get("surface")
				row = {
					"present": actual != expected_support
					if actual in {"ground", "seat", "work_surface", "product"}
					else None,
					"evidence": support.get("evidence"),
				}
			row = row if isinstance(row, dict) else {}
			value, evidence = row.get("present"), row.get("evidence")
			valid = type(value) is bool and isinstance(evidence, str) and bool(evidence.strip())
			rows.append(
				dict(frame=index, present=value if valid else None, evidence=str(evidence or "")[:500])
			)
		bad = [r for r in rows if r["present"] is True]
		unknown = [r for r in rows if r["present"] is None]
		witnesses = bad or unknown or rows
		results.append(
			dict(
				id="geometry." + key,
				dimension="physics",
				claim=claim,
				verdict="violated" if bad else "uncertain" if unknown or not rows else "supported",
				frames=[r["frame"] for r in witnesses],
				reason="; ".join(
					r["evidence"] or "Missing or malformed physical evidence." for r in witnesses
				)[:1000],
				observations=rows,
			)
		)
	return results


DESCRIBE = """You are a film continuity supervisor. Describe this frame objectively; do not guess what is hidden.
If no foreground actor or character is present, set figures to an empty array; do not add a "no figure present" placeholder.
Return JSON:
{{"figures": [{{"who": "short description",
  "body_pose": "standing, seated, kneeling, lying, or unclear, based on visible weight support",
  "supported_by": "what carries its weight: floor, seat, bed, table, product package, or nothing visible",
  "passes_through": "furniture or object that any part of its body overlaps or passes through, or empty",
  "cut_by_surface": "the furniture edge that splits its body into a part above and a part hidden below, for example a tabletop with the chest on top and the legs under it, or empty",
  "size_vs_support": "smaller, similar or larger compared with the furniture it sits on, stands on or leans on"}}],
 "human_body_parts": true if any real human hand, arm, face or person is visible,
 "product_packages": number of separate {product} packages visible,
 "other_retail_packages": number of other standalone branded retail packages or cartons visible, excluding flat artwork,
 "product_placement": {{"supported_by": "the visible surface or object carrying the advertised product, or nothing visible",
  "contact": "flush, floating, intersecting, or unclear",
  "perspective": "aligned, misaligned, or unclear compared with its visible support and environment",
  "scale": "plausible, implausible, or unclear compared with nearby objects at the same depth",
  "occlusion": "plausible, implausible, none, or unclear",
  "shadow": "grounded, missing_or_mismatched, or unclear",
  "lighting": "matched, mismatched, or unclear; compare the product's light direction, colour temperature and edges with its immediate surroundings"}},
 "main_table": {{"fully_visible": true only if the entire working tabletop and all of its base are in frame,
  "leg_count": number of DISTINCT legs visibly attached to that tabletop and reaching the floor, or null if occluded,
  "malformed": true only if a table leg visibly floats, fuses with the actor or joins a different tabletop}},
 "medium": "photographic", "3d_render" or "2d_illustration",
 "rule_conflicts": ["each scene rule below that the frame clearly contradicts, with the visible evidence"]}}
Scene rules: {rules}"""

SURFACE_OF_PRODUCT = re.compile(r"\b(?:product|package|packet|pack|box|tissue)\b", re.I)
WORK_SURFACE = re.compile(r"\b(?:table|tabletop|counter|countertop|desk|shelf|worktop)\b", re.I)
NOTHING = {"", "none", "nothing", "no", "n/a", "empty", "null"}
PERSON_ROLES = {"person", "people", "talent"}
CHARACTER_ROLES = {"character", *PERSON_ROLES}
ABSENT_FIGURE = re.compile(
	r"^(?:no|none|zero)\s+(?:figure|person|people|character|actor|mascot|bear)s?\b", re.I
)
LIMB_TOPOLOGY_PROMPT = (
	"Compare ONLY mascot/person anatomy in these two images, including visible ears and limbs. "
	"Image 1 is the selected source pose; image 2 is a rendered scene. "
	"Determine whether the rendered subject has any visibly elongated or narrowed "
	"limb relative to its torso compared with source, any extra or fused paw/hand, "
	"or any limb attached at an impossible place. "
	"Check that visible ears retain the source count, shape and attachment: do not accept a clearly missing ear in a comparable unobstructed front view. "
	"Ignore normal perspective and ordinary occlusion, and never infer hidden ears or limbs. A different arm position "
	"(raised, bent, extended forward, wrapped around or holding an object) is not "
	"elongation: compare each limb's length and thickness relative to the torso, "
	"not where the limb points. Return one JSON object "
	"with exactly these top-level keys: distortion (true, false, or null), "
	"evidence (string). "
	"Return true for a clearly missing or changed visible ear too. Return false only when the comparable visible ears and limbs retain the reference anatomy; use null when those features cannot be compared."
)
TOPOLOGY_SCHEMA = {
	"type": "object",
	"additionalProperties": False,
	"required": ["distortion", "evidence"],
	"properties": {
		"distortion": {"type": ["boolean", "null"]},
		"evidence": {"type": "string", "minLength": 1},
	},
}


RETAIL_FORMS = {
	"enclosed_retail_volume",
	"single_loose_sheet",
	"folded_loose_material",
	"other_noncontainer",
	"unclear",
}
RETAIL_FORM_PROMPT = (
	"Observe each foreground inanimate object held by or near the character. Exclude the character and room furniture. "
	"Classify physical form from visible geometry alone. enclosed_retail_volume is a retail wrapper/carton enclosing a stack "
	"or volume, with visible container faces, closure/seams or package thickness. A single thin flexible sheet, even "
	"folded/crumpled/printed, is single_loose_sheet or folded_loose_material, never enclosed_retail_volume merely because "
	"of a drawing or brand context. Report objects [{physical_form,visible_evidence}]. Use unclear if form cannot be resolved."
)
RETAIL_FORM_SCHEMA = {
	"type": "object",
	"additionalProperties": False,
	"required": ["objects"],
	"properties": {
		"objects": {
			"type": "array",
			"maxItems": 20,
			"items": {
				"type": "object",
				"additionalProperties": False,
				"required": ["physical_form", "visible_evidence"],
				"properties": {
					"physical_form": {"type": "string", "enum": sorted(RETAIL_FORMS)},
					"visible_evidence": {"type": "string", "minLength": 10},
				},
			},
		}
	},
}
REFERENCE_FIT_SCHEMA = {
	"type": "object",
	"additionalProperties": False,
	"required": ["comparable", "identity_match", "proportions_match", "anatomy_connected", "reason"],
	"properties": {
		"comparable": {"type": "boolean"},
		**{
			key: {"type": ["boolean", "null"]}
			for key in ("identity_match", "proportions_match", "anatomy_connected")
		},
		"reason": {"type": "string", "minLength": 1},
	},
}


def retail_container_count(observation):
	"""Derive counts from explicit object forms, not a contradictory model total."""
	rows = observation.get("objects") if isinstance(observation, dict) else None
	if not isinstance(rows, list):
		return None
	for row in rows:
		if (
			not isinstance(row, dict)
			or row.get("physical_form") not in RETAIL_FORMS
			or row["physical_form"] == "unclear"
			or not isinstance(row.get("visible_evidence"), str)
			or len(row["visible_evidence"].strip()) < 10
		):
			return None
	return sum(row["physical_form"] == "enclosed_retail_volume" for row in rows)


def _product_placement_issues(description):
	"""Return only clear product/environment conflicts reported by the visual reviewer.

	The reviewer owns the visual observation.  These rules deliberately do not infer a
	world model from prompt text: ``unclear`` is not a failure, while a floating pack,
	wrong perspective, or an impossible occlusion is a reason for the existing targeted
	redraw path to try again.
	"""
	placement = description.get("product_placement") or {}
	if not isinstance(placement, dict):
		return []

	def value(key):
		return str(placement.get(key) or "").strip().casefold()

	issues = []
	if value("contact") == "floating":
		issues.append("Critical geometry: advertised product floats above its visible support")
	elif value("contact") == "intersecting":
		issues.append("Critical geometry: advertised product intersects its visible support")
	if value("perspective") == "misaligned":
		issues.append("Critical geometry: advertised product perspective conflicts with the environment")
	if value("scale") == "implausible":
		issues.append("Critical geometry: advertised product scale conflicts with nearby objects")
	if value("occlusion") == "implausible":
		issues.append(
			"Critical geometry: advertised product has an impossible foreground/background occlusion"
		)
	if value("shadow") == "missing_or_mismatched":
		issues.append("Critical geometry: advertised product is not grounded by a matching contact shadow")
	if value("lighting") == "mismatched":
		issues.append(
			"Critical geometry: advertised product lighting or cutout edge conflicts with the environment"
		)
	return issues


def _product_angle_fit_findings(source, frame, ask):
	"""Check package orientation against the scene's actual support plane.

	A broad product identity comparison can preserve the printed front while
	missing that the whole box was pasted at the wrong camera angle. Keep this
	separate from artwork identity and abstain if the support is not visible.
	"""
	answer = ask(
		[source, frame],
		"Image 1 is the selected product source; image 2 is the composed scene. "
		"Judge only whether the rendered package camera orientation and its receding "
		"box edges are physically plausible relative to the immediate support and "
		"camera view in image 2. An upright-looking front pasted across a differently "
		"angled support is false. Do not judge label text. "
		"Return JSON answer true, false or null and reason.",
		max_edge=768,
	)
	if not isinstance(answer, dict) or answer.get("answer") is None:
		return ["Physical staging review: product angle against its support remains unverified."]
	if answer.get("answer") is False:
		return ["Critical geometry: advertised product camera angle conflicts with its support plane"]
	return []


def _rules(project, shot_number):
	"""The scene's own Logic / Liên tục text, as authored in the template or written by the AI director."""
	try:
		source = frappe.parse_json(project.storyboard_source_json or "{}") or {}
		scenes = (source.get("selected_demo") or {}).get("scenes") or []
		return str((scenes[int(shot_number) - 1] or {}).get("continuity") or "").strip()
	except (IndexError, TypeError, ValueError):
		return ""


def reference_fit_findings(shot, frame, ask=None):
	"""Compare the rendered subjects with the exact references bound to this shot.

	A scene can be physically supported yet redraw a mascot with long arms or a
	different head/body ratio. Compare visible invariant geometry separately from
	the general scene description, and abstain when cropping or occlusion prevents
	a fair comparison. The mask/cutout path keeps RGB pixels exact; this check also
	covers reference-guided frames and unexpected redraws.
	"""
	if ask is None:
		from joymedia.services.review.consistency import ask
	issues = []
	for row in shot.generation_inputs or []:
		role = frappe.scrub(row.reference_role or "")
		if role not in {"character", "person", "product"} or not row.asset_version:
			continue
		url = frappe.db.get_value("Asset Version", row.asset_version, "file")
		if not url:
			issues.append(f"Reference fit review: {role} source image is unavailable.")
			continue
		if role in {"character", "person"}:
			analysis = (
				frappe.parse_json(
					frappe.db.get_value("Asset Version", row.asset_version, "analysis_json") or "{}"
				)
				or {}
			)
			# A generated pose is a staging aid, not the identity authority. Always
			# compare the frame with the customer's original character as well.
			canonical = analysis.get("source_asset_version")
			identity_url = frappe.db.get_value("Asset Version", canonical, "file") if canonical else url
			if not identity_url:
				issues.append("Reference fit review: original character identity image is unavailable.")
				identity_url = url
			if analysis.get("source_asset_version"):
				from joymedia.services.planning.pose_assets import _qualified_pose_metadata

				if not _qualified_pose_metadata(analysis):
					issues.append(
						"Critical identity: selected generated character view has stale or missing pose qualification"
					)
			# Identity similarity is a poor proxy for anatomy: the general reviewer
			# has accepted frames with a recognisable face but stretched arms. Ask
			# about limb topology separately, against the actual selected pose.
			limbs = ask(
				[url, frame],
				LIMB_TOPOLOGY_PROMPT,
				max_edge=768,
				schema=TOPOLOGY_SCHEMA,
			)
			if (
				not isinstance(limbs, dict)
				or type(limbs.get("distortion")) is not bool
				or not isinstance(limbs.get("evidence"), str)
				or not limbs["evidence"].strip()
			):
				issues.append(f"Reference fit review: {role} limb topology remains unverified.")
			elif limbs["distortion"]:
				evidence = str(
					limbs.get("evidence") or "visible limb proportions differ from the selected pose"
				).strip()[:180]
				issues.append(
					f"Critical geometry: {role} limb topology differs from its selected reference: {evidence}"
				)
			prompt = (
				"Image 1 is the selected character reference and image 2 is the rendered scene. "
				"Compare only visible invariant character traits, allowing a changed pose, camera angle, "
				"lighting, crop and ordinary occlusion: head-to-torso ratio, torso width, limb length "
				"and thickness relative to the torso, appendage count, face design, colour, material "
				"and defining accessories. Do not infer hidden body parts. "
			)
		else:
			issues.extend(_product_angle_fit_findings(url, frame, ask))
			prompt = (
				"Image 1 is the selected product reference and image 2 is the rendered scene. "
				"Compare only visible product facts shared by both images, allowing camera perspective, "
				"crop, lighting and genuine occlusion: overall package proportions, panel shape, "
				"logo and readable front artwork. Do not judge unseen sides as factual. "
			)
		answer = ask(
			[identity_url if role in {"character", "person"} else url, frame],
			prompt
			+ "Return JSON with comparable boolean, identity_match boolean or null, "
			+ "proportions_match boolean or null, anatomy_connected boolean or null, and reason string. "
			+ "If the subject is too small or hidden for a reliable comparison, comparable=false "
			+ "and use null for unknown findings. Never treat an uncertain match as true.",
			max_edge=768,
			schema=REFERENCE_FIT_SCHEMA,
		)
		if role in {"character", "person"}:
			from joymedia.services.planning.pose_assets import (
				EYE_DESIGN_QUESTION,
				HEAD_ACCESSORY_QUESTION,
				KNOWN_EYE_SHAPES,
				character_look,
			)

			# A broad paired comparison can overlook a small but defining feature.
			# Observe each image independently so the source traits are not copied
			# into a description of a changed frame. The eye question explicitly
			# excludes characters printed on the product package.
			source_eyes = (ask(identity_url, EYE_DESIGN_QUESTION, max_edge=1024) or {}).get("eye_shape")
			frame_eyes = (ask(frame, EYE_DESIGN_QUESTION, max_edge=1024) or {}).get("eye_shape")
			# A smiling (^ ^) and a sleeping closed-eye drawing are different designs.
			closed_drawings = {"closed_smiling_arcs", "closed_sleeping_arcs"}
			if (
				source_eyes in KNOWN_EYE_SHAPES
				and frame_eyes in KNOWN_EYE_SHAPES
				and (
					source_eyes.startswith("closed") != frame_eyes.startswith("closed")
					or ({source_eyes, frame_eyes} <= closed_drawings and source_eyes != frame_eyes)
				)
			):
				issues.append(f"Critical identity: {role} eye design changed from the original reference")
			# Every check passed a smooth vinyl mascot redrawn as a fluffy plush teddy.
			source_surface = character_look(identity_url).get("surface")
			frame_surface = character_look(frame).get("surface")
			if source_surface and frame_surface and source_surface != frame_surface:
				issues.append(
					f"Critical identity: {role} surface changed from {source_surface} to {frame_surface}"
				)
			source_head = (ask(identity_url, HEAD_ACCESSORY_QUESTION, max_edge=768) or {}).get(
				"head_accessories"
			)
			frame_head = (ask(frame, HEAD_ACCESSORY_QUESTION, max_edge=768) or {}).get("head_accessories")
			# Additions are observable even if the original has no accessory.
			# Absence in a frame can merely mean that the head is out of view.
			if source_head == [] and isinstance(frame_head, list) and frame_head:
				issues.append(
					f"Critical identity: {role} has new head accessories absent from the original reference"
				)
		if not isinstance(answer, dict) or answer.get("comparable") is not True:
			issues.append(
				f"Reference fit review: {role} identity and proportions are not visible well enough to verify."
			)
			continue
		role_critical = False
		if answer.get("identity_match") is False:
			issues.append(f"Critical identity: {role} in first frame differs from its selected reference")
			role_critical = True
		if answer.get("proportions_match") is False:
			issues.append(
				f"Critical identity: {role} body or package part ratios differ from its selected reference"
			)
			role_critical = True
		if role in {"character", "person"} and answer.get("anatomy_connected") is False:
			issues.append(f"Critical geometry: {role} has disconnected or distorted anatomy")
			role_critical = True
		if answer.get("identity_match") is not True or answer.get("proportions_match") is not True:
			if not role_critical:
				issues.append(f"Reference fit review: {role} identity or part ratios remain unverified.")
	return list(dict.fromkeys(issues))


def actor_count_findings(observation, expected):
	"""Require an independent body count before admitting a character scene.

	The detailed geometry description can merge two similar mascots into one
	figure. A separate count checks the full frame, including occluded bodies.
	"""
	if not isinstance(observation, dict) or type(observation.get("actor_instances")) is not int:
		return ["Physical staging review: the number of character bodies remains unverified."]
	count = observation["actor_instances"]
	if count != expected:
		return [f"Critical prop: {count} character bodies are visible; the script declares {expected}."]
	return []


def compare(
	description, *, human_cast, has_product, medium_locked, close_framing, cast_count=None, expected_pose=""
):
	"""Turn a frame description into the scene's clear violations (empty when it is physically coherent)."""
	issues = []
	figures = [
		figure
		for figure in description.get("figures") or []
		if isinstance(figure, dict) and not ABSENT_FIGURE.match(str(figure.get("who") or "").strip())
	]
	if cast_count and len(figures) > cast_count:
		issues.append(
			f"Critical prop: {len(figures)} characters drawn instead of {cast_count}; the cast appears twice"
		)
	if cast_count == 0 and figures:
		issues.append(
			"Critical prop: a foreground actor appears in a product-only shot with no declared cast"
		)
	for figure in figures:
		who = str(figure.get("who") or "the character")[:80]
		observed_pose = str(figure.get("body_pose") or "").strip().casefold()
		if expected_pose == "upright_supported" and observed_pose in {"seated", "kneeling", "lying"}:
			issues.append(
				f"Critical geometry: {who} is {observed_pose} although the scripted opening requires standing"
			)
		if expected_pose == "seated_supported" and observed_pose == "standing":
			issues.append(
				f"Critical geometry: {who} is standing although the scripted opening requires sitting"
			)
		through = str(figure.get("passes_through") or "").strip()
		if through.lower() not in NOTHING:
			issues.append(f"Critical geometry: {who} passes through {through[:80]}")
		cut = str(figure.get("cut_by_surface") or "").strip()
		support = str(figure.get("supported_by") or "").lower()
		# The vision model calls ordinary foreground occlusion a "cut" even on a
		# valid floor-seated frame. Require a second independent cue before making
		# that claim an automatic GPU retry. An invalid table support is itself a
		# sufficient cue; a reported solid-body intersection is another.
		if cut.lower() not in NOTHING and (through.lower() not in NOTHING or WORK_SURFACE.search(support)):
			issues.append(f"Critical geometry: {who} passes through {cut[:80]}, half above and half below it")
		if SURFACE_OF_PRODUCT.search(support):
			issues.append(
				f"Critical geometry: {who} rests on the advertised product instead of a floor or seat"
			)
		elif WORK_SURFACE.search(support):
			issues.append(
				f"Critical geometry: {who} rests on a table or work surface instead of a seat or the floor"
			)
		elif "nothing" in support and not close_framing:
			issues.append(f"Critical geometry: {who} has no visible support")
		if (
			str(figure.get("size_vs_support") or "").lower().startswith("larger")
			and support not in NOTHING
			and not re.search(r"\b(?:floor|ground|earth)\b", support)
		):
			issues.append(f"Critical geometry: {who} is larger than the furniture it uses")
	if description.get("human_body_parts") is True and not human_cast:
		issues.append("Critical prop: a human hand, arm or person appears; only the cast may act")
	try:
		packages = int(description.get("product_packages") or 0)
	except (TypeError, ValueError):
		packages = 0
	if has_product and packages > 1:
		issues.append(f"Critical prop: {packages} product packages are drawn instead of one")
	try:
		other_packages = int(description.get("other_retail_packages") or 0)
	except (TypeError, ValueError):
		other_packages = 0
	if not has_product and (packages or other_packages):
		issues.append("Critical prop: unreferenced retail packages appear in a product-free shot")
	if has_product and other_packages:
		issues.append("Critical prop: unrelated retail packages appear beside the advertised product")
	if has_product:
		issues.extend(_product_placement_issues(description))
	table = description.get("main_table") or {}
	if isinstance(table, dict):
		if table.get("malformed") is True:
			issues.append(
				"Critical geometry: a working-table leg is floating, fused or attached to the wrong surface"
			)
	if medium_locked and str(description.get("medium") or "").lower().startswith("2d"):
		issues.append(
			"Critical style: the frame is a flat 2D illustration; the references are photographed 3D figures"
		)
	for conflict in (description.get("rule_conflicts") or [])[:2]:
		if str(conflict).strip():
			issues.append(f"Critical geometry: breaks the scene rule: {str(conflict).strip()[:200]}")
	return list(dict.fromkeys(issues))


def frame_findings(project, shot, frame):
	"""Review one first frame against its actual scene and selected references.

	An incomplete vision response is an unresolved review, never evidence that
	the frame satisfies the physical contract.
	"""
	from joymedia.services.planning.prompts import MEDIUM_LOCK, _mood
	from joymedia.services.planning.shot_structure import structure_for
	from joymedia.services.review.consistency import ask

	roles = [
		str(role or "").casefold()
		for role in frappe.get_all("Shot Reference", filters={"parent": shot.name}, pluck="reference_role")
	]
	structure = structure_for(shot) or {}
	description = ask(
		frame,
		DESCRIBE.format(
			product=project.product_name or "advertised product",
			rules=_rules(project, shot.shot_number) or "none beyond normal physics",
		),
		max_edge=768,
	)
	if not isinstance(description, dict):
		return ["Physical staging review: the visual observer returned no usable description."]
	gaps = []
	objects = ask(frame, RETAIL_FORM_PROMPT, max_edge=1024, schema=RETAIL_FORM_SCHEMA)
	containers = retail_container_count(objects)
	description["broad_package_counts"] = {
		key: description.get(key) for key in ("product_packages", "other_retail_packages")
	}
	description["retail_object_observations"] = objects
	# This narrow observation owns the count. Unknown form remains a blocker;
	# it must not manufacture a claim that an authored sheet is a retail pack.
	description["product_packages"] = (containers or 0) if "product" in roles else 0
	description["other_retail_packages"] = (containers or 0) if "product" not in roles else 0
	if containers is None:
		gaps.append(
			"Critical prop: retail container form remains unverified; do not remove authored loose materials by guessing."
		)
	if not isinstance(description.get("figures"), list):
		gaps.append(
			"Physical staging review: the visual observer did not describe the figures; support remains unverified."
		)
	if "product" in roles:
		placement = description.get("product_placement")
		if not isinstance(placement, dict) or any(
			str(placement.get(key) or "").strip().casefold() in {"", "unclear", "unknown"}
			for key in ("contact", "perspective", "scale", "lighting")
		):
			gaps.append(
				"Physical staging review: product contact, perspective, scale or lighting remain unverified."
			)
		matte = ask(
			frame,
			"Look immediately around the advertised package where it meets the scene. "
			"Is there a visible rectangular white or studio-background patch pasted over the "
			"table, floor or room, making the product appear to be a flat photo overlay? "
			"Ignore naturally white packaging and a deliberately full-white end card. "
			"Return JSON answer true, false or null and a short reason.",
			max_edge=768,
		)
		if isinstance(matte, dict) and matte.get("answer") is True:
			gaps.append(
				"Critical geometry: product retains a rectangular studio-background matte in the scene"
			)
		elif not isinstance(matte, dict) or matte.get("answer") is not False:
			gaps.append("Physical staging review: product background matte remains unverified.")
	declared_actors = sum(role in CHARACTER_ROLES for role in roles)
	issues = compare(
		description,
		human_cast=bool(PERSON_ROLES.intersection(roles)),
		has_product="product" in roles,
		medium_locked=MEDIUM_LOCK in _mood(project, avoid=False),
		close_framing=structure.get("framing") in {"close_up", "extreme_close_up"},
		cast_count=declared_actors,
		expected_pose=(frappe.parse_json(shot.motion_plan_json or "{}") or {})
		.get("pose_requirement", {})
		.get("opening_pose", ""),
	)
	if declared_actors:
		count = ask(
			frame,
			"Count the separate physical character or person bodies in this full frame. "
			"Include a body even when partly hidden behind furniture or another character. "
			"Exclude characters printed on product packaging, pictures and reflections. "
			"Return JSON actor_instances integer or null, and reason. Count bodies, not heads or paws.",
			max_edge=768,
		)
		issues.extend(actor_count_findings(count, declared_actors))
	issues.extend(reference_fit_findings(shot, frame, ask=ask))
	if not PERSON_ROLES.intersection(roles):
		outsider = ask(
			frame,
			"Inspect the extreme left and right edges and foreground of this image. "
			"Are any real human heads, hair, shoulders, hands or bodies visible, even partially cropped? "
			"Do not count a mascot printed on product packaging. "
			"Return JSON unexpected_humans true, false or null and reason.",
			max_edge=768,
		)
		if outsider.get("unexpected_humans") is True:
			issues.append("Critical prop: an undeclared human appears in the frame foreground or edge")
		elif outsider.get("unexpected_humans") is not False:
			gaps.append("Physical staging review: partial foreground people remain unverified.")
	return [*issues, *gaps]


def audit_frames(project, shots, audited):
	"""Audit each new first frame that passed the standard checks; mark violations for scene repair.

	``audited`` maps shot name -> the frame already audited, so a frame is asked about once.
	Returns the names of shots that were marked for review.
	"""
	marked = []
	for shot in shots:
		# Every drawn frame without a critical finding yet: mild review notes do not
		# prove the frame is physically right.
		if (
			not shot.keyframe_artifact
			or shot.consistency_status in {"Checking", "Redrawing"}
			or "Critical" in str(shot.consistency_notes or "")
		):
			continue
		if audited.get(shot.name) == shot.keyframe_artifact:
			continue
		frame = frappe.db.get_value("Generation Artifact", shot.keyframe_artifact, "frappe_file")
		if not frame:
			continue
		try:
			issues = frame_findings(project, shot, frame)
		except Exception:
			# The batch can continue to a provisional review, but an unavailable
			# observer cannot qualify this frame as physically sound.
			frappe.log_error(title=f"Physical audit skipped for {shot.name}")
			issues = [
				"Physical staging review: the visual observer was unavailable; support and placement remain unverified."
			]
		audited[shot.name] = shot.keyframe_artifact
		if issues:
			frappe.db.set_value(
				"Shot",
				shot.name,
				{
					"consistency_status": "Needs Review",
					"consistency_notes": "; ".join([*issues, shot.consistency_notes or ""]).strip("; ")[
						:1000
					],
				},
				update_modified=False,
			)
			shot.consistency_status = "Needs Review"
			shot.consistency_notes = "; ".join(issues)
			marked.append(shot.name)
	return marked
