"""Product view planning and explicitly-labelled AI extrapolation.

A supplied product photo remains the factual source of truth.  When a script
needs an angle that is absent from supplied material, this module can prepare an
*AI-extrapolated candidate* before storyboard rendering.  The candidate is
conditioned by the real pack image and reviewed for visible colour/artwork
retention, but it is deliberately marked unverified: a single photograph cannot
establish hidden panels, ingredients, barcodes or folds.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import frappe

from joymedia.services.project.reference_lineage import original_reference
from joymedia.services.scene.references import identity_key, value

_VIEW_PATTERNS = (
	("front_left", re.compile(r"\bfront[- ]left(?:[- ](?:three[- ]quarter|3/4))?\b", re.I)),
	("front_right", re.compile(r"\bfront[- ]right(?:[- ](?:three[- ]quarter|3/4))?\b", re.I)),
	("top_front", re.compile(r"\btop[/ -]front\b", re.I)),
	("back", re.compile(r"\b(?:back|rear|reverse)\b", re.I)),
	("left", re.compile(r"\b(?:left(?:[- ]hand)?|left[- ]side)\b", re.I)),
	("right", re.compile(r"\b(?:right(?:[- ]hand)?|right[- ]side)\b", re.I)),
	("side", re.compile(r"\b(?:side|profile|end panel)\b", re.I)),
	("front", re.compile(r"\b(?:front|face[- ]on)\b", re.I)),
	("three_quarter", re.compile(r"\b(?:three[- ]quarter|3/4|angled|oblique)\b", re.I)),
)
_PRODUCT_NOUN = r"(?:product|pack|packet|package|box|bottle)"
_VIEW_NOUN = r"(?:view|angle|shot|panel|face|profile|orientation)"
PRODUCT_IDENTITY_QUALIFICATION_VERSION = 3


def _explicit_product_view_text(text):
	"""Ignore scene furniture/camera directions that do not describe the pack.

	A ``side table`` near a pack or an oblique room shot is not evidence that
	the script requested a new product side panel. Only angle phrases attached
	to the product and a view/panel term request a new media candidate.
	"""
	text = str(text or "")
	for kind, pattern in _VIEW_PATTERNS:
		for match in pattern.finditer(text):
			if re.match(r"\s+(?:table|room|wall|window|chair|shelf)\b", text[match.end() :], re.I):
				continue
			before = text[max(0, match.start() - 45) : match.start()]
			after = text[match.end() : match.end() + 45]
			view_then_product = re.search(
				rf"\b{_VIEW_NOUN}\b\s+(?:of\s+)?(?:the\s+)?(?:advertised\s+)?{_PRODUCT_NOUN}\b",
				after,
				re.I,
			)
			product_then_view = re.search(rf"\b{_PRODUCT_NOUN}\b.{{0,20}}\b{_VIEW_NOUN}\b", after, re.I)
			preceding_product = re.search(rf"\b{_PRODUCT_NOUN}\b.{{0,25}}$", before, re.I)
			view_after = re.match(rf"\s*{_VIEW_NOUN}\b", after, re.I)
			profile_of_product = kind == "side" and re.match(
				rf"\s+of\s+(?:the\s+)?{_PRODUCT_NOUN}\b", after, re.I
			)
			if (
				view_then_product
				or product_then_view
				or (preceding_product and view_after)
				or profile_of_product
			):
				return kind
	return "source"


def product_view_kind(row):
	"""Infer the visible source viewpoint from user-owned descriptive metadata.

	``source`` deliberately means that no label claims an angle.  It is still a
	valid immutable reference, but is not falsely advertised as a front view.
	"""
	explicit = str(value(row, "product_view") or "").strip().casefold()
	if explicit in {
		"front",
		"front_left",
		"front_right",
		"top_front",
		"three_quarter",
		"side",
		"left",
		"right",
		"back",
	}:
		return explicit
	text = " ".join(str(value(row, field) or "") for field in ("label", "keep_rule", "description", "view"))
	for kind, pattern in _VIEW_PATTERNS:
		if pattern.search(text):
			return kind
	return "source"


def multiview_reconstruction_inputs(project, canonical_key):
	"""Return verified input views for the upstream Hunyuan3D multi-view contract.

	Hunyuan3D's multi-view pipeline takes real photographs keyed as ``front``,
	``left``, ``back`` and ``right``. A single labelled pack photo must never be
	expanded into invented slots: that would turn unknown package artwork into
	fake evidence. ``ready`` is therefore false until at least two distinct
	declared views exist, including a front view. Callers may retain the source
	view while waiting for sufficient client evidence.
	"""
	rows = _product_rows(project, canonical_key)
	by_view = {}
	for row in rows:
		view = product_view_kind(row)
		if (
			view in {"front", "left", "right", "back"}
			and _analysis(row).get("product_view_status")
			not in {"ai_extrapolated_candidate", "supplied_sheet_crop_unverified"}
			and view not in by_view
		):
			by_view[view] = row
	# The upstream accepts 1--4 views, but image-to-3D from one branded view
	# cannot establish hidden printed surfaces. Requiring front plus one more
	# actual view makes this a reconstruction input contract, not hallucination.
	ready = "front" in by_view and len(by_view) >= 2
	return {
		"ready": ready,
		"identity_key": identity_key(rows[0]) if rows else "",
		"views": by_view,
		"missing": [view for view in ("front", "left", "back", "right") if view not in by_view],
		"reason": ""
		if ready
		else "Hunyuan3D multi-view reconstruction needs a declared front photo and at least one additional real product view.",
	}


def requested_product_view(plan):
	"""Return a requested *opening* product view, never a later video action."""
	explicit = str(plan.get("product_view") or "").strip().casefold()
	if explicit in {
		"front",
		"front_left",
		"front_right",
		"top_front",
		"three_quarter",
		"side",
		"left",
		"right",
		"back",
	}:
		return explicit
	text = " ".join(str(plan.get(field) or "") for field in ("image_prompt", "start_state", "setting_prompt"))
	# Rotation in a later video action is not an opening-frame request.  The
	# first frame must be grounded before the video model is asked to animate it.
	return _explicit_product_view_text(text)


def requested_product_view_for_scene(scene):
	"""Read the Director's shot description, never the available product views.

	This keeps the dependency in the intended direction: script -> required
	view -> prepared media -> storyboard.  ``source`` means the script has no
	opening-angle requirement and therefore does not justify another candidate.
	"""
	explicit = str(scene.get("product_view") or "").strip().casefold()
	if explicit in {
		"front",
		"front_left",
		"front_right",
		"top_front",
		"three_quarter",
		"side",
		"left",
		"right",
		"back",
	}:
		return explicit
	return _explicit_product_view_text(
		" ".join(str(scene.get(field) or "") for field in ("image_prompt", "start_state", "visual_camera"))
	)


def _product_rows(project, canonical_key):
	rows = list(project.get("selected_media") or [])
	selected = next((row for row in rows if value(row, "reference_key") == canonical_key), None)
	if not selected:
		return []
	identity = identity_key(selected)
	return [
		row
		for row in rows
		if identity_key(row) == identity and str(value(row, "reference_role") or "").casefold() == "product"
	]


def _analysis(row):
	"""Read generated-view metadata without making plain unit-test rows depend on Frappe."""
	embedded = value(row, "analysis_json")
	if isinstance(embedded, dict):
		return embedded
	if embedded:
		try:
			return frappe.parse_json(embedded) or {}
		except Exception:
			return {}
	version = value(row, "asset_version")
	if not version:
		return {}
	try:
		return frappe.parse_json(frappe.db.get_value("Asset Version", version, "analysis_json") or "{}") or {}
	except Exception:
		return {}


def is_extrapolated_product_view(row):
	analysis = _analysis(row)
	return analysis.get("product_view_status") == "ai_extrapolated_candidate" or bool(
		analysis.get("source_asset_version") and not analysis.get("product_view_status")
	)


def _view_candidate_qualified(row):
	analysis = _analysis(row)
	status = analysis.get("product_view_status")
	if is_extrapolated_product_view(row):
		return (
			status == "ai_extrapolated_candidate"
			and analysis.get("view_geometry_verified") is True
			and analysis.get("visible_source_retained") is True
			and analysis.get("view_physical_plausibility_verified") is True
			and analysis.get("product_identity_qualification_version")
			== PRODUCT_IDENTITY_QUALIFICATION_VERSION
		)
	if status in {
		"ai_extrapolated_candidate",
		"supplied_sheet_crop_unverified",
		"operator_masked_view_unverified",
	}:
		return analysis.get("view_geometry_verified") is True
	return True


def _candidate_key(source, view):
	identity = identity_key(source)
	version = value(source, "asset_version")
	digest = hashlib.sha256(
		f"{identity}:{version}:{view}:identity_v{PRODUCT_IDENTITY_QUALIFICATION_VERSION}".encode()
	).hexdigest()[:12]
	return f"product_view_{digest}"


def product_view_requirements(script):
	"""Return unique non-source views the completed Director script requests."""
	required = []
	for scene in script.get("scenes") or []:
		view = requested_product_view_for_scene(scene)
		if view == "source":
			continue
		for key in scene.get("products") or scene.get("reference_keys") or []:
			entry = (str(key), view)
			if entry not in required:
				required.append(entry)
	return required


def requested_view_sequence(creative_direction):
	"""Return product angles explicitly listed by the client in order."""
	direction = str(creative_direction or "")
	mentions = []
	# A brief can mention an angle as a prohibition or limitation (for example,
	# "Do not invent hidden side printing"). That text is not a shot request.
	# Scope angle extraction to affirmative sentences containing a product and
	# a view term, so a distant negative instruction cannot contaminate it.
	for sentence in re.split(r"(?<=[.!?])\s+|[\n;]+", direction):
		if not re.search(rf"\b{_PRODUCT_NOUN}\b", sentence, re.I):
			continue
		if not re.search(r"\b(?:angles?|views?|sides?|perspectives?)\b", sentence, re.I):
			continue
		if re.search(
			r"\b(?:do not|don't|never|avoid|without|cannot|can't|missing|unverified)\b", sentence, re.I
		):
			continue
		occupied = []
		for kind, pattern in _VIEW_PATTERNS:
			for match in pattern.finditer(sentence):
				if any(match.start() < end and match.end() > start for start, end in occupied):
					continue
				occupied.append(match.span())
				mentions.append((direction.find(sentence) + match.start(), kind))
	views = [kind for _, kind in sorted(mentions) if kind != "front"]
	return list(dict.fromkeys(views))


def apply_requested_view_sequence(script, creative_direction):
	"""Carry a client's explicit angle sequence into product-bearing shots.

	The prose writer can omit these instructions, leaving view preparation with
	an empty requirement list. Only explicit product-angle directions are used;
	generated views remain unverified candidates until their normal checks.
	"""
	views = requested_view_sequence(creative_direction)
	if not views:
		return script
	product_scenes = [
		(index, scene)
		for index, scene in enumerate(script.get("scenes") or [])
		if scene.get("products") and requested_product_view_for_scene(scene) == "source"
	]
	# Prefer shots whose opening composition actually shows the package. A
	# character close-up should not consume the first requested product angle.
	product_scenes.sort(
		key=lambda item: (
			not bool(re.search(rf"\b{_PRODUCT_NOUN}\b", str(item[1].get("visual_camera") or ""), re.I)),
			item[0],
		)
	)
	for (_, scene), view in zip(product_scenes, views, strict=False):
		if requested_product_view_for_scene(scene) != "source":
			continue
		label = view.replace("_", "-")
		scene["product_view"] = view
		scene["visual_camera"] = (
			str(scene.get("visual_camera") or "").rstrip(" .")
			+ f". Opening product view: {label} view of the advertised pack."
		)
	return script


def _palette_retained(source_file, candidate):
	"""A cheap independent guard: reject candidates that lose the source palette.

	This is intentionally only a palette check. It does not pretend to prove
	unknown packaging artwork is authentic.
	"""
	import cv2
	import numpy as np

	source = cv2.imread(str(source_file))
	generated = cv2.imdecode(np.frombuffer(candidate, dtype=np.uint8), cv2.IMREAD_COLOR)
	if source is None or generated is None:
		return False
	source = cv2.resize(source, (128, 128), interpolation=cv2.INTER_AREA)
	generated = cv2.resize(generated, (128, 128), interpolation=cv2.INTER_AREA)

	# Ignore white/grey studio backgrounds. They otherwise dominate the
	# histogram and make a blue pack correlate with a pink pack.
	def histogram(image):
		hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
		chromatic = ((hsv[:, :, 1] > 65) & (hsv[:, :, 2] > 65)).astype(np.uint8) * 255
		hue = cv2.calcHist([hsv], [0], chromatic, [36], [0, 180]).ravel()
		return hue / hue.sum() if hue.sum() else hue

	source_hue, generated_hue = histogram(source), histogram(generated)
	if not source_hue.any() and not generated_hue.any():
		# A monochrome package has no informative hue. Preserve the earlier
		# saturation/value comparison for that case instead of rejecting it.
		def monochrome_histogram(image):
			hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
			return cv2.normalize(cv2.calcHist([hsv], [1, 2], None, [16, 16], [0, 256, 0, 256]), None)

		return (
			cv2.compareHist(monochrome_histogram(source), monochrome_histogram(generated), cv2.HISTCMP_CORREL)
			>= 0.35
		)
	if not source_hue.any() or not generated_hue.any():
		return False
	return float(np.minimum(source_hue, generated_hue).sum()) >= 0.35


# The user enabled product angles "as long as the colour and the information of the
# product are not distorted" (2026-10-31). Both are measured, not judged in a pair.
STRICT_HUE_OVERLAP = 0.7
FRONT_VISIBLE_VIEWS = {"front", "front_left", "front_right", "top_front", "three_quarter"}
PRINT_TRANSCRIPTION = (
	"Read every piece of printed text visible on the product package, exactly as printed, including brand name, "
	"product name, numbers, units and small lines. Do not translate or correct spelling. Return JSON lines: an "
	"array of strings, one per printed line."
)
PRINT_SCHEMA = {
	"type": "object",
	"additionalProperties": False,
	"required": ["lines"],
	"properties": {"lines": {"type": "array", "items": {"type": "string"}}},
}


def _hue_histogram(image):
	import cv2

	hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
	chromatic = ((hsv[:, :, 1] > 65) & (hsv[:, :, 2] > 65)).astype("uint8") * 255
	hue = cv2.calcHist([hsv], [0], chromatic, [36], [0, 180]).ravel()
	return hue / hue.sum() if hue.sum() else hue


def _colour_retained(source_file, candidate):
	"""The pack's colours, background ignored, overlap strongly and keep the same dominant hue."""
	import cv2
	import numpy as np

	source = cv2.imread(str(source_file))
	generated = cv2.imdecode(np.frombuffer(candidate, dtype=np.uint8), cv2.IMREAD_COLOR)
	if source is None or generated is None:
		return False
	source_hue = _hue_histogram(cv2.resize(source, (256, 256), interpolation=cv2.INTER_AREA))
	generated_hue = _hue_histogram(cv2.resize(generated, (256, 256), interpolation=cv2.INTER_AREA))
	if not source_hue.any() or not generated_hue.any():
		return _palette_retained(source_file, candidate)  # A monochrome pack keeps the tonal check.
	shift = abs(int(source_hue.argmax()) - int(generated_hue.argmax()))
	return (
		float(np.minimum(source_hue, generated_hue).sum()) >= STRICT_HUE_OVERLAP
		and min(shift, 36 - shift) <= 1
	)


def _printed_words(image):
	"""The words printed on the pack, read on their own (never beside another picture)."""
	from joymedia.services.review.consistency import ask

	if isinstance(image, str | Path) and Path(image).is_file():
		image = Path(image).read_bytes()  # A filesystem path (the identity photo) is read directly.
	lines = (ask(image, PRINT_TRANSCRIPTION, max_edge=1024, schema=PRINT_SCHEMA) or {}).get("lines")
	if not isinstance(lines, list):
		return None
	return {word for line in lines for word in re.findall(r"\w+", str(line).casefold())}


def _information_retained(source_file, candidate, view):
	"""No new or changed printed word, and every word kept while the front face is in view."""
	source, generated = _printed_words(source_file), _printed_words(candidate)
	if not source or generated is None:
		return False
	if generated - source:
		return False
	return view not in FRONT_VISIBLE_VIEWS or not (source - generated)


MIN_FACE_MATCHES, MIN_FACE_INLIERS = 12, 15


def restore_printed_face(source_file, candidate):
	"""Put the photograph's real print back on a generated angle of the same pack.

	The video model redrew small print as nonsense at every new angle ("900" for
	"400", 13 of 13 candidates on 2026-10-31) while the logo, mascot and stripes
	stayed recognisable. Those features locate the pack's printed face; the
	photograph's pack (not its backdrop) is warped onto it in perspective, so the
	angle keeps its shape and the words are the photograph's own. None when the
	face cannot be located reliably.
	"""
	import cv2
	import numpy as np

	source = cv2.imread(str(source_file))
	generated = cv2.imdecode(np.frombuffer(candidate, dtype=np.uint8), cv2.IMREAD_COLOR)
	if source is None or generated is None:
		return None
	sift = cv2.SIFT_create(4000)
	source_points, source_features = sift.detectAndCompute(cv2.cvtColor(source, cv2.COLOR_BGR2GRAY), None)
	points, features = sift.detectAndCompute(cv2.cvtColor(generated, cv2.COLOR_BGR2GRAY), None)
	if source_features is None or features is None or len(source_points) < 2 or len(points) < 2:
		return None
	pairs = cv2.BFMatcher().knnMatch(source_features, features, k=2)
	good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
	if len(good) < MIN_FACE_MATCHES:
		return None
	homography, inliers = cv2.findHomography(
		np.float32([source_points[m.queryIdx].pt for m in good]),
		np.float32([points[m.trainIdx].pt for m in good]),
		cv2.RANSAC,
		5.0,
	)
	if homography is None or int(inliers.sum()) < MIN_FACE_INLIERS:
		return None
	height, width = generated.shape[:2]
	pack = (cv2.cvtColor(source, cv2.COLOR_BGR2GRAY) < 245).astype(np.uint8) * 255  # not the white backdrop
	pack = cv2.morphologyEx(pack, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
	mask = cv2.erode(cv2.warpPerspective(pack, homography, (width, height)), np.ones((5, 5), np.uint8))
	alpha = cv2.GaussianBlur(mask, (7, 7), 0)[..., None] / 255.0
	restored = (
		cv2.warpPerspective(source, homography, (width, height)) * alpha + generated * (1 - alpha)
	).astype(np.uint8)
	ok, encoded = cv2.imencode(".png", restored)
	return encoded.tobytes() if ok else None


def _candidate_matches_visible_source(source_url, candidate):
	"""Require an observer to preserve observable, rather than hidden, facts."""
	from joymedia.services.review.consistency import ask

	result = ask(
		[source_url, candidate],
		"Image 1 is a real product photograph. Image 2 is an AI-generated alternate-view candidate. "
		"Judge ONLY visible facts shared with image 1: main colour palette, product category, overall pack "
		"shape/proportions, clearly visible logo/front artwork, and exact readable printed numbers or quantity. "
		"Separately check the visible package panel proportions (allow perspective, not a shorter/taller package), "
		"the arrangement of logo and printed illustration, and every readable line on faces shared by both images. "
		"Missing or replaced print on a shared visible face is a failure, even if the logo and colours match. "
		"A different colour variant, sheet count, ply count, or logo is a different product and must be false. "
		"Do not assume hidden side or rear "
		"printing is factual. Return JSON identity_retained, proportions_retained, shared_print_retained "
		"(boolean or null for each), and reason string. True requires visible evidence; unknown is null.",
		max_edge=1024,
		schema={
			"type": "object",
			"additionalProperties": False,
			"required": ["identity_retained", "proportions_retained", "shared_print_retained", "reason"],
			"properties": {
				**{
					key: {"type": ["boolean", "null"]}
					for key in ("identity_retained", "proportions_retained", "shared_print_retained")
				},
				"reason": {"type": "string", "minLength": 1},
			},
		},
	)
	return (
		isinstance(result, dict)
		and isinstance(result.get("reason"), str)
		and bool(result["reason"].strip())
		and all(
			result.get(key) is True
			for key in ("identity_retained", "proportions_retained", "shared_print_retained")
		)
	)


def _candidate_physically_plausible(source_url, candidate):
	"""Plausibility is independent of branding similarity and the requested camera angle."""
	from joymedia.services.planning.pose_assets import BINARY_REVIEW_SCHEMA, _affirmed
	from joymedia.services.review.consistency import ask

	return _affirmed(
		ask(
			[source_url, candidate],
			"Image 1 is the original product. Inspect only physical plausibility in image 2: exactly one "
			"complete object, connected components, coherent volume and perspective, stable visible support, "
			"and the original type of material and construction. A soft wrapped package must not become a "
			"rigid carton, nor may a rigid object melt or fuse. Do not assume every object is a rectangular box. "
			"An isolated transparent cutout need not include a scene or ground; a removed background is not evidence of floating. "
			"Ignore printed branding for this independent check. Return answer true only with clear physical "
			"evidence, false for a defect, null when uncertain, and reason.",
			max_edge=768,
			schema=BINARY_REVIEW_SCHEMA,
		)
	)


def _candidate_matches_requested_view(candidate, view):
	"""Check observable camera geometry separately from package identity."""
	from joymedia.services.planning.pose_assets import BINARY_REVIEW_SCHEMA, _affirmed
	from joymedia.services.review.consistency import ask

	if view in {"front_left", "front_right", "left", "right"}:
		result = ask(
			candidate,
			"Inspect the rectangular product package. Which narrow END panel is visibly exposed "
			"beside its broad printed front face: the viewer-left end, viewer-right end, neither, "
			"or unclear? Return JSON visible_end exactly one of left, right, neither, unclear; reason.",
			max_edge=768,
			schema={
				"type": "object",
				"additionalProperties": False,
				"required": ["visible_end", "reason"],
				"properties": {
					"visible_end": {"type": "string", "enum": ["left", "right", "neither", "unclear"]},
					"reason": {"type": "string", "minLength": 1},
				},
			},
		)
		expected = "left" if view in {"front_left", "left"} else "right"
		return (
			result.get("visible_end") == expected
			and isinstance(result.get("reason"), str)
			and bool(result["reason"].strip())
		)
	if view == "top_front":
		result = ask(
			candidate,
			"Is the product shown from above with BOTH its top face and broad front face visibly "
			"exposed? Return JSON answer true, false or null and reason.",
			max_edge=768,
			schema=BINARY_REVIEW_SCHEMA,
		)
		return _affirmed(result)
	if view == "side":
		result = ask(
			candidate,
			"Is a narrow end or side face the dominant visible face of this product package, "
			"rather than the broad printed front face? Return JSON answer true, false or null and reason.",
			max_edge=768,
			schema=BINARY_REVIEW_SCHEMA,
		)
		return _affirmed(result)
	if view in {"front", "back", "three_quarter"}:
		return _affirmed(
			ask(
				candidate,
				f"Observe the product's actual camera view without assuming that it follows its prompt. "
				f"Is it visibly a {view.replace('_', ' ')} product view? Front means the main front face "
				"is dominant; back means the rear is dominant; three-quarter means a coherent oblique view "
				"with multiple sides visible. Use the actual object geometry rather than assuming a cuboid. "
				"Return JSON answer true, false or null if the viewpoint cannot be established, and reason.",
				max_edge=768,
				schema=BINARY_REVIEW_SCHEMA,
			)
		)
	return False


def _observed_hero_view(candidate, requested):
	"""The view a candidate actually shows; None when it fits no acceptable view.

	The video model zoomed and tilted the pack rather than rotating it (2026-10-31).
	For a requested angle that keeps the print in view, the view it really shows is
	recorded and used (a top-down or front detail is still a new view of the exact
	pack); a side or back request stays strict.
	"""
	if _candidate_matches_requested_view(candidate, requested):
		return requested
	if requested not in FRONT_VISIBLE_VIEWS:
		return None
	for other in ("top_front", "three_quarter", "front_left", "front_right"):
		if other != requested and _candidate_matches_requested_view(candidate, other):
			return other
	return "front"


def _generate_candidate(project, source, view, observed=None):
	"""Try H3 product-view candidates, respecting an explicit image-workflow override."""
	from joymedia.services.keyframes.locations import _keyframe_workflow
	from joymedia.services.project.context import _project_settings
	from joymedia.services.project.formats import preparation_dimensions
	from joymedia.services.workflows.comfyui import run_workflow_to_bytes, upload_frappe_file
	from joymedia.services.workflows.resolver import build_execution_workflow, get_workflow_input_contract
	from joymedia.workflow_adapters import get_workflow_adapter

	configured = frappe.conf.get("joymedia_product_view_workflow")
	source_url = frappe.db.get_value("Asset Version", source.asset_version, "file")
	if not source_url:
		raise ValueError("The product source has no image file.")
	identity = original_reference(source.asset_version)
	identity_path = frappe.get_doc("File", {"file_url": identity["file"]}).get_full_path()

	def accepts(content):
		"""The picture to use (the candidate, or it with the photograph's print restored), or False."""
		try:
			if not (_palette_retained(identity_path, content) and _colour_retained(identity_path, content)):
				return False
			if not _information_retained(identity_path, content, view):
				restored = restore_printed_face(identity_path, content)
				if restored and _colour_retained(identity_path, restored):
					content = restored
				# Otherwise the candidate stays as drawn: accepted on colour, its print unverified (user).
			if not (
				_candidate_matches_visible_source(identity["file"], content)
				and _candidate_physically_plausible(identity["file"], content)
			):
				return False
			shown = _observed_hero_view(content, view)
			if not shown:
				return False
			if observed is not None:
				observed["view"] = shown
			return content
		except Exception:
			frappe.log_error(title=f"Product angle observation failed; {view} sample rejected")
			return False

	if not configured:
		from joymedia.services.planning.reference_bridges import product_view_from_h3

		try:
			return product_view_from_h3(project, source, view, accepts)
		except ValueError:
			frappe.log_error(title="H3 product-view preparation deferred; trying configured image fallback")
	workflow = (
		frappe.get_doc("Generation Workflow", configured) if configured else _keyframe_workflow(project)
	)
	if not any(row["role"] == "product" for row in get_workflow_input_contract(workflow)):
		raise ValueError("The selected product-view workflow lacks a product reference input.")
	product = upload_frappe_file(source_url)["server_path"]
	width, height = preparation_dimensions(_project_settings(project))
	direction = {
		"front": "front-facing",
		"front_left": "front three-quarter with the package's narrow LEFT end panel visible at image left",
		"front_right": "front three-quarter with the package's narrow RIGHT end panel visible at image right",
		"top_front": "elevated top-and-front",
		"three_quarter": "three-quarter",
		"left": "left-side three-quarter",
		"right": "right-side three-quarter",
		"side": "near-90-degree SIDE PROFILE: the narrow end panel dominates the image; the broad printed front "
		"is visible only as a thin sliver at one edge",
		"back": "rear three-quarter",
	}[view]
	prompt = (
		"Commercial studio product-reference image of exactly one packaged product on a pure white (#FFFFFF) "
		"seamless background, with no gray gradient or colored backdrop. "
		f"Camera: {direction} view. Use the supplied product image as the sole identity and artwork anchor. "
		"Retain its visible silhouette, dimensions, material, dominant colour palette, logo and front-panel artwork. "
		"Where the requested view exposes an unseen panel, extrapolate a simple physically plausible continuation "
		"of the visible colour system; do not invent factual claims, small print, barcodes, certification marks, "
		"ingredients, or a different brand. No people, mascot, furniture, hands, text overlays or second package."
	)
	stored = frappe.parse_json(workflow.workflow_json)
	output = get_workflow_adapter(workflow).extract_execution_metadata(stored)["primary_output_node_key"]
	for attempt in range(3):
		graph = build_execution_workflow(
			workflow,
			inputs={"generation_prompt": prompt, "product": [product]},
			seed=int(
				hashlib.sha256(f"{source.asset_version}:{view}:{attempt}".encode()).hexdigest()[:12], 16
			),
			width=width,
			height=height,
			fps=float(workflow.output_fps or 24),
			frame_count=1,
			output_prefix=f"joymedia/product-views/{frappe.generate_hash(length=10)}",
		)
		content = run_workflow_to_bytes(graph, output, forget=True)
		accepted = accepts(content)
		if accepted:
			return accepted if isinstance(accepted, bytes | bytearray) else content
		# Keep evidence outside selectable Product media. A rejected artifact is
		# useful for diagnosing a model/configuration change, but must never be
		# accidentally used by the storyboard as if it were client-approved.
		evidence = Path(frappe.get_site_path("private", "joymedia-product-view-rejections"))
		evidence.mkdir(parents=True, exist_ok=True)
		(evidence / f"{_candidate_key(source, view)}-{attempt}.png").write_bytes(content)
	raise ValueError(f"No {view} product candidate retained the observable source identity.")


def _prepared_view_result(source, view, candidate, strict):
	return {
		"source": source,
		"view": view,
		"candidate": candidate,
		"status": "source_locked" if strict else "ready",
		**(
			{
				"fallback": source,
				"reason": "Generated angle is an inferred preview; exact artwork stays bound to the supplied photograph.",
			}
			if strict
			else {}
		),
	}


def prepare_script_product_views(project, script):
	"""Prepare script-required one-image product candidates before storyboard import.

	Generated assets are added to Product media and remain explicitly marked as
	unverified extrapolations. The method returns deferred evidence rather than
	blocking the entire project when a candidate cannot pass review.
	"""
	prepared = []
	selected = list(project.get("selected_media") or [])
	by_key = {str(value(row, "reference_key") or ""): row for row in selected}
	for source_key, view in product_view_requirements(script):
		source = by_key.get(source_key)
		if not source or str(value(source, "reference_role") or "").casefold() != "product":
			continue
		variants = _product_rows(project, source_key)
		strict = _source_pixels_locked(project, [source_key], by_key)
		if any(
			product_view_kind(row) == view
			and _view_candidate_qualified(row)
			and not is_extrapolated_product_view(row)
			for row in variants
		):
			prepared.append({"source": source_key, "view": view, "status": "supplied"})
			continue
		candidate_key = _candidate_key(source, view)
		existing = by_key.get(candidate_key)
		if existing and _view_candidate_qualified(existing):
			prepared.append(_prepared_view_result(source_key, view, candidate_key, strict))
			continue
		try:
			observed = {}
			content = _generate_candidate(project, source, view, observed)
			shown = observed.get("view", view)
			identity = original_reference(source.asset_version)
			from joymedia.services.planning.reference_bridges import frame_provenance

			bridge_provenance = frame_provenance(project, content)
			from joymedia.services.intake.subject_cutout import cutout_studio_reference, sam2_configured

			mask_evidence = None
			if sam2_configured():
				content, mask_evidence = cutout_studio_reference(content)
				identity_path = frappe.get_doc("File", {"file_url": identity["file"]}).get_full_path()
				if not (
					_candidate_matches_visible_source(identity["file"], content)
					and _observed_hero_view(content, view)
					and _candidate_physically_plausible(identity["file"], content)
					and _colour_retained(identity_path, content)
				):
					raise ValueError(
						"The final masked product view no longer retains its original traits and geometry."
					)
			# Recorded, not required: a print that could not be restored is shown for review (user).
			information_verified = _information_retained(
				frappe.get_doc("File", {"file_url": identity["file"]}).get_full_path(), content, view
			)
			frappe.db.commit()
			from joymedia.services.intake.assets import create_media_asset

			image = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"{candidate_key}.png",
					"content": content,
					"is_private": 1,
					"attached_to_doctype": "Media Project",
					"attached_to_name": project.name,
				}
			).insert(ignore_permissions=True)
			asset = create_media_asset(
				f"{value(source, 'label') or source_key} {shown} AI candidate",
				"Product",
				file_url=image.file_url,
				file_name=image.name,
				source="Generated",
			)
			frappe.db.set_value(
				"Asset Version",
				asset["asset_version"],
				{
					"analysis_status": "Ready",
					"analysis_json": frappe.as_json(
						{
							"kind": "product",
							"product_view": shown,
							"requested_view": view,
							"product_view_status": "ai_extrapolated_candidate",
							"source_asset_version": value(source, "asset_version"),
							"identity_source_asset_version": identity["asset_version"],
							"identity_source_sha256": identity["content_hash"],
							"preparation_bridge": bridge_provenance,
							"visible_source_retained": True,
							"product_identity_qualification_version": PRODUCT_IDENTITY_QUALIFICATION_VERSION,
							"view_geometry_verified": True,
							"view_physical_plausibility_verified": True,
							"colour_verified": True,
							"information_verified": information_verified,
							"subject_cutout": mask_evidence,
							"unknown_panels": "inferred; unverified against real packaging",
						}
					),
				},
				update_modified=False,
			)
			project.reload()
			project.append(
				"selected_media",
				{
					"asset_version": asset["asset_version"],
					"reference_key": candidate_key,
					"identity_key": identity_key(source),
					"reference_role": "Product",
					"label": f"{value(source, 'label') or source_key} {shown} (AI candidate)",
					"relative_size": value(source, "relative_size"),
					"keep_rule": value(source, "keep_rule"),
					"product_view": shown,
				},
			)
			project.save(ignore_permissions=True)
			project.reload()
			new_row = next(row for row in project.selected_media if row.reference_key == candidate_key)
			selected.append(new_row)
			by_key[candidate_key] = new_row
			prepared.append(_prepared_view_result(source_key, view, candidate_key, strict))
		except Exception as exc:
			frappe.log_error(frappe.get_traceback(), f"Product-view candidate deferred for {project.name}")
			# This is a safe automatic fallback, not a stopped production
			# state. ``constrain_product_views`` will bind the original source
			# view and lock the scene camera to it rather than allowing the
			# storyboard to draw counterfeit packaging from the failed request.
			prepared.append(
				{
					"source": source_key,
					"view": view,
					"status": "source_locked",
					"fallback": source_key,
					"reason": str(exc)[:300],
				}
			)
	return prepared


def prepare_script_product_cutouts(project, script):
	"""Prepare an exact-pixel matte for each scripted opening product view.

	The selected photo or validated novel-view candidate remains the artwork
	source. This step changes alpha only, and the view binder later prefers the
	matte for scene compositing. It never invents a camera angle.
	"""
	from joymedia.services.intake.subject_cutout import ensure_transparent_reference, sam2_configured

	if not sam2_configured():
		return []
	prepared = []
	seen = set()
	for scene in script.get("scenes") or []:
		desired = requested_product_view_for_scene(scene)
		for key in scene.get("products") or []:
			if (key, desired) in seen:
				continue
			seen.add((key, desired))
			source = next((row for row in project.selected_media or [] if row.reference_key == key), None)
			if not source or str(source.reference_role).casefold() != "product":
				continue
			chosen, _ = _choose_view(
				_product_rows(project, key),
				desired,
				allow_extrapolated=not _source_pixels_locked(
					project, [key], {r.reference_key: r for r in project.selected_media or []}
				),
			)
			if chosen:
				try:
					masked = ensure_transparent_reference(project, chosen)
					prepared.append(
						{"source": key, "view": desired, "cutout": masked.reference_key, "status": "ready"}
					)
				except Exception as exc:
					frappe.log_error(frappe.get_traceback(), f"Product matte deferred for {project.name}")
					prepared.append(
						{"source": key, "view": desired, "status": "needs_review", "reason": str(exc)[:300]}
					)
	return prepared


@frappe.whitelist()
def prepare_product_view_candidates(project_name, script):
	"""Queueable/API entry point for script-led product-view preparation."""
	project = frappe.get_doc("Media Project", project_name)
	project.check_permission("write")
	if isinstance(script, str):
		script = frappe.parse_json(script) or {}
	return prepare_script_product_views(project, script or {})


@frappe.whitelist()
def enqueue_product_view_candidates(project_name, script):
	"""Submit preparation outside the request worker; return the background job id."""
	project = frappe.get_doc("Media Project", project_name)
	project.check_permission("write")
	if isinstance(script, str):
		script = frappe.parse_json(script) or {}
	job = frappe.enqueue(
		"joymedia.services.planning.product_views.prepare_product_view_candidates",
		queue="long",
		timeout=1800,
		project_name=project.name,
		script=script or {},
	)
	return job.id


def _choose_view(rows, desired, *, allow_extrapolated=True):
	if not allow_extrapolated:
		rows = [row for row in rows if not is_extrapolated_product_view(row)]

	def preferred(candidates):
		# A reviewed silhouette is compositable; an opaque sheet crop is only
		# visual guidance. Both retain the same declared camera view.
		return (
			next(
				(
					row
					for row in reversed(candidates)
					if (
						(_analysis(row).get("subject_cutout") or {})
						.get("visual_mask_review", {})
						.get("clean")
						is True
						and (_analysis(row).get("subject_cutout") or {}).get("edge_roughness", 999) <= 1.25
					)
					or _analysis(row).get("product_view_status") == "operator_masked_view_unverified"
				),
				candidates[0],
			)
			if candidates
			else None
		)

	if desired != "source":
		exact = preferred(
			[
				row
				for row in rows
				if product_view_kind(row) == desired
				and _view_candidate_qualified(row)
				and not is_extrapolated_product_view(row)
			]
		)
		if not exact:
			exact = next(
				(
					row
					for row in rows
					if (product_view_kind(row) == desired or _analysis(row).get("requested_view") == desired)
					and _view_candidate_qualified(row)
				),
				None,
			)
		if exact:
			return exact, True
	# Prefer a declared front image for ordinary product presentation.  A source
	# photo with no declared view remains preferred to a guessed virtual view.
	fallback = preferred(
		[
			row
			for row in rows
			if product_view_kind(row) == "front"
			and _view_candidate_qualified(row)
			and not is_extrapolated_product_view(row)
		]
	)
	if not fallback:
		fallback = preferred(
			[row for row in rows if _view_candidate_qualified(row) and not is_extrapolated_product_view(row)]
		)
	if not fallback:
		raise ValueError(
			"No qualified product source view is available; generated views cannot replace a missing original."
		)
	return fallback, desired == "source"


HELD = re.compile(
	r"\b(?:hold|holds|holding|grip|grips|gripping|carry|carries|carrying|clutch|clutches|clutching)\b", re.I
)


def _unheld_opening(image_prompt, notes):
	"""Rewrite an opening still that has the locked product in a paw or hand.

	The planner is told the product rests untouched, but repeated "holding the
	pack" anyway. Check its answer, as the pose planner checks prop verbs, and
	ask once for the same still with the product resting on its support.
	"""
	text = str(image_prompt or "")
	if not HELD.search(text):
		return text
	from joymedia.services.planning.production import _ask_planner

	try:
		answer = _ask_planner(
			"Rewrite this opening still so the advertised product rests untouched on its support, its printed "
			"face toward the camera, and nobody holds, grips or carries anything yet. Keep every subject, the "
			"place, the framing and each body's support; any handling happens later in the video. "
			"Return JSON image_prompt string. Source: " + text,
			system="You correct an opening still for an exact product overlay.",
			capability="planner",
			sampling_profile="production_plan",
			response_schema={
				"type": "object",
				"properties": {"image_prompt": {"type": "string"}},
				"required": ["image_prompt"],
				"additionalProperties": False,
			},
		)
		rewritten = " ".join(str((answer or {}).get("image_prompt") or "").split())
	except Exception:
		rewritten = ""
	if rewritten and not HELD.search(rewritten):
		notes.append("Opening still rewritten so the locked product rests untouched.")
		return rewritten
	notes.append("Opening still still describes the locked product held; the product lock will judge it.")
	return text


def _silhouette_phrase(project, view_keys, rows):
	"""The product's on-screen proportions, measured from its own cutout.

	The lock pastes the photo without stretching and rejects footprint changes.
	A measured matte from the pinned source preparation is also usable for an
	opaque upload; its image crop must not substitute for the object's outline. Words such as
	"same proportions as its photo" did not reach the picture model: it drew a
	1.8:1 pack lying on its side as a near-square box. A number does.
	"""
	from PIL import Image

	from joymedia.services.keyframes.overlay import _cutout_path

	for key in view_keys:
		row = rows.get(key)
		version = value(row, "asset_version") if row else None
		path = _cutout_path(version) if version else None
		ratio = None
		if path:
			try:
				with Image.open(path) as image:
					box = (
						image.convert("RGBA").getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
					)
				if box:
					ratio = (box[2] - box[0]) / (box[3] - box[1])
			except OSError:
				continue
		elif version:
			from joymedia.services.consistency.retention import policy, source_outline

			source_hash = frappe.db.get_value("Asset Version", version, "content_hash")
			frozen = policy() or {}
			if source_hash and frozen.get("recipe_sha256"):
				outline = source_outline(source_hash, frozen)
				ratio = outline.get("width_height_ratio")
		if not isinstance(ratio, (int, float)) or not 0 < ratio < float("inf"):
			continue
		if ratio >= 1.15:
			return f"lying on its long side, its outline about {ratio:.1f} times as wide as it is tall, "
		if ratio <= 1 / 1.15:
			return f"standing upright, its outline about {1 / ratio:.1f} times as tall as it is wide, "
		return "its outline about as wide as it is tall, "
	return ""


def _source_pixels_locked(project, view_keys, rows):
	"""Whether the GPU source-pixel lock will replace this shot's drawn product."""
	from joymedia.services.consistency.retention import policy
	from joymedia.services.intake.references import preservation_modes

	if not policy():
		return False
	# Absent workbook choices mean the strict source_pixels default.
	modes = preservation_modes(project) if hasattr(project, "selected_media") else {}
	return any(
		modes.get(value(rows[key], "asset_version"), "source_pixels") != "reference_guided"
		for key in view_keys
		if rows.get(key)
	)


def _product_only(plan, rows):
	"""A shot whose references include no character or person."""
	return not any(
		str(value(rows[key], "reference_role") or "").casefold() in {"character", "person"}
		for key in plan.get("reference_keys") or []
		if rows.get(key)
	)


def constrain_product_views(project, plan, required_view=None):
	"""Constrain each visible product identity to one truthful source view.

	Returns the plan for ergonomic chaining.  It writes ``reference_views`` used
	by the shot binder, plus human-readable planner notes.  Existing explicit
	product views from a workbook are honored only if they belong to the chosen
	source view; an unsupported prompt request is downgraded to the available
	view rather than creating synthetic package artwork.
	"""
	keys = list(dict.fromkeys(plan.get("reference_keys") or []))
	notes = list(plan.get("notes") or [])
	explicit = list(dict.fromkeys(plan.get("reference_views") or []))
	rows = {value(row, "reference_key"): row for row in project.get("selected_media") or []}
	selected_views = []
	# The authored opening camera direction outranks the production model's
	# paraphrase. The latter often drops the angle while retaining the pack.
	desired = required_view or requested_product_view(plan)

	for key in keys:
		canonical = rows.get(key)
		if not canonical or str(value(canonical, "reference_role") or "").casefold() != "product":
			continue
		variants = _product_rows(project, key)
		if not variants:
			continue
		locked = _source_pixels_locked(project, [key], rows)
		if locked and _product_only(plan, rows):
			# A product-only shot shows the product image itself (no drawn product for the
			# source lock to replace): a generated angle whose colour and printed words were
			# measured against the photo may be used; any other candidate may not.
			variants = [
				row
				for row in variants
				if not is_extrapolated_product_view(row) or _analysis(row).get("colour_verified")
			]
			locked = False
		chosen, supported = _choose_view(variants, desired, allow_extrapolated=not locked)
		selected_views.append(value(chosen, "reference_key"))
		available = ", ".join(dict.fromkeys(product_view_kind(row) for row in variants))
		chosen_text = (
			f"the unverified AI {product_view_kind(chosen)} candidate"
			if is_extrapolated_product_view(chosen)
			else "the supplied source photograph"
			if product_view_kind(chosen) == "source"
			else f"the supplied {product_view_kind(chosen)} source view"
		)
		if is_extrapolated_product_view(chosen):
			notes.append(
				"Product-view candidate: AI-extrapolated from one supplied angle; preserve its observable palette "
				"and artwork, but treat unseen panels as inferred and unverified. Human product-art review is required."
			)
		elif _analysis(chosen).get("product_view_status") == "supplied_sheet_crop_unverified":
			notes.append(
				"Product-view reference: cropped from a supplied multi-angle sheet on white. "
				"Use only its visible printed faces; hidden panels and print remain unverified."
			)
		elif _analysis(chosen).get("product_view_status") == "operator_masked_view_unverified":
			notes.append(
				"Product-view reference: transparent cutout from a supplied photograph. "
				"The source print is preserved; verify its outline, perspective, contact and occlusion in the scene."
			)
		if not supported:
			notes.append(
				f"Product-view contract: requested {desired} view is not supplied; "
				f"use {chosen_text} only (available: {available})."
			)
		else:
			notes.append(
				f"Product-view contract: use {chosen_text} only; do not synthesize unseen packaging panels."
			)

	if selected_views:
		non_product_explicit = [
			key
			for key in explicit
			if not (rows.get(key) and str(value(rows[key], "reference_role") or "").casefold() == "product")
		]
		plan["reference_views"] = list(dict.fromkeys([*non_product_explicit, *selected_views]))
		# The image prompt is fed to a model that draws the setting.  State the
		# contract there as well, so it does not invent a second/different pack
		# behind the exact source-art overlay.
		locked = _source_pixels_locked(project, selected_views, rows)
		if locked:
			plan["image_prompt"] = _unheld_opening(plan.get("image_prompt"), notes)
		angles = {product_view_kind(rows[key]) for key in selected_views}
		angle_label = next(iter(angles)) if len(angles) == 1 else "source"
		plan["image_prompt"] = (
			str(plan.get("image_prompt") or "").rstrip(". ")
			+ f". Product orientation is locked to the selected {angle_label} view; do not invent unseen packaging geometry or printed surfaces. "
			"Align the visible package base and receding edges with the support plane and camera perspective; "
			+ (
				# The source-pixel lock replaces exactly one detected pack with the
				# photo. It rejects a second pack, a tilted outline and any paw over
				# it, so a "load-bearing grip" opening could never pass. State its
				# acceptance conditions on the first drawing, not after a rejection.
				"show exactly one package, resting with broad, visible contact on its table or floor, "
				+ _silhouette_phrase(project, selected_views, rows)
				+ "its photographed face toward the camera, fully in frame and not held, lifted or covered by any "
				"paw or hand; any handling begins after this opening frame."
				if locked
				else "the package must make broad, visible contact with its table or floor, or have a visible load-bearing grip."
			)
		)
	plan["notes"] = list(dict.fromkeys(notes))
	return plan
