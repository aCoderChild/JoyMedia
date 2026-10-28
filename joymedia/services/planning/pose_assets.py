"""Prepare reusable character poses after the director script, before visual storyboards.

Uses the project's registered Klein image workflow and its native character
reference binding. CharacterPose's reference -> pose-library -> scene workflow
inspired this stage; its sprite-specific nodes are deliberately not loaded into
the 3D mascot renderer. Generated images are selectable views of the same
identity, never replacements for the customer's original photograph.
"""

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import frappe

HELD_PROP_QUESTION = (
	"Count separate objects physically held between or against the character's paws or arms. "
	"Do not count flowers, hats, bows or other accessories attached to the head. "
	"Return JSON with integer held_object_count (0 if none) and names of held objects in held_objects array."
)

EYE_DESIGN_QUESTION = (
	"Describe the visible eye drawing on the main physical three-dimensional character only. "
	"Ignore any character printed on product packaging, posters or screens. "
	"If the main character is turned away, cropped, or its eyes cannot be resolved, say not_visible or unclear. "
	"Return JSON eye_shape exactly one of closed_arcs, open_dots, "
	"open_other, closed_other, not_visible, unclear; include reason."
)

POSE_QUALIFICATION_VERSION = 2

HEAD_ACCESSORY_QUESTION = (
	"Describe accessories physically worn on the central character's head (flowers, bows, hats, "
	"ribbons, crowns). Ignore objects held in paws and graphics printed on products. "
	"Return JSON head_accessories as a list of short lowercase names (empty list if none), and reason."
)


def _eye_design_instruction(source_image, angle):
	if angle != "front":
		return ""
	from joymedia.services.review.consistency import ask

	shape = ask(source_image, EYE_DESIGN_QUESTION, max_edge=768).get("eye_shape")
	return {
		"closed_arcs": "Keep both eyes as closed curved arcs exactly as the source; do not open them. ",
		"open_dots": "Keep both eyes as open round dots exactly as the source. ",
		"closed_other": "Keep the source's closed-eye design exactly; do not open the eyes. ",
		"open_other": "Keep the source's open-eye design exactly. ",
	}.get(shape, "")


def _qualified_pose_metadata(analysis):
	"""Return the stable, reviewed pose contract for a generated Character view.

	Intake captions are refreshed over time, so they cannot be the sole source of
	truth for a view that passed pose review. Earlier checks missed facial marks
	and accessories, so their cached qualifications cannot be reused automatically.
	"""
	analysis = analysis or {}
	if not analysis.get("source_asset_version"):
		return None
	if analysis.get("pose_qualification_version") != POSE_QUALIFICATION_VERSION:
		return None
	pose = analysis.get("qualified_pose_and_support") or analysis.get("pose_and_support")
	view = analysis.get("qualified_pose_view") or analysis.get("view")
	if not pose:
		return None
	return {"source_asset_version": analysis["source_asset_version"], "pose": str(pose), "view": view}


def _qualified_view_for_requirement(selected, identity_key, requirement, requested_view):
	"""Find reviewed evidence that can actually open the scripted action.

	The Director is free to write an action that is absent from the customer's
	photos.  It is not free to bind a seated view to a locomotion opening merely
	because that view was mentioned in the screenplay.  This is a semantic
	compatibility check between the script-derived body requirement and reusable
	media; it does not encode any character, product, or project-specific pose.
	"""
	needed = {"upright_supported": "mobile_or_upright", "seated_supported": "seated_supported"}.get(
		requirement
	)
	if not needed:
		return None, None
	from joymedia.services.planning.pose_coverage import source_pose_state

	candidates = []
	for row in selected:
		if row.get("identity_key") != identity_key or str(row.get("reference_role") or "").casefold() not in {
			"character",
			"person",
		}:
			continue
		try:
			analysis = (
				frappe.parse_json(
					frappe.db.get_value("Asset Version", row.get("asset_version"), "analysis_json") or "{}"
				)
				or {}
			)
		except Exception:
			analysis = {}
		qualified = _qualified_pose_metadata(analysis)
		if qualified and source_pose_state([qualified["pose"]]) == needed:
			candidates.append((row, qualified))
	if not candidates:
		return None, None
	# View is part of the shot composition, but support is the admission
	# criterion.  A front view remains a better fallback than quietly returning
	# to the seated source image.
	return next(
		((row, qualified) for row, qualified in candidates if qualified.get("view") == requested_view),
		candidates[0],
	)


def _silhouette_aspect(image):
	"""Measure the main foreground on a plain studio background with OpenCV.

	A missing/complex matte returns None; it never becomes evidence of a match.
	This is a guard against humanising a squat mascot, not a pose detector.
	"""
	import cv2
	import numpy as np

	if isinstance(image, str):
		path = (
			frappe.get_doc("File", {"file_url": image}).get_full_path()
			if image.startswith(("/private/files/", "/files/"))
			else image
		)
		pixels = cv2.imread(str(path))
	else:
		pixels = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
	if pixels is None:
		return None
	height, width = pixels.shape[:2]
	if min(height, width) < 128:
		return None
	pixels = pixels.astype(np.float32)
	corner = max(8, min(height, width) // 20)
	background = np.median(
		np.concatenate(
			[
				pixels[:corner, :corner].reshape(-1, 3),
				pixels[:corner, -corner:].reshape(-1, 3),
				pixels[-corner:, :corner].reshape(-1, 3),
				pixels[-corner:, -corner:].reshape(-1, 3),
			]
		),
		axis=0,
	)
	# Only use the metric when all corners actually share a near-uniform backdrop.
	if any(
		np.linalg.norm(np.median(pixels[y, x].reshape(-1, 3), axis=0) - background) > 25
		for y in (slice(0, corner), slice(-corner, None))
		for x in (slice(0, corner), slice(-corner, None))
	):
		return None
	mask = (np.linalg.norm(pixels - background, axis=2) > 18).astype(np.uint8)
	n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
	if n < 2:
		return None
	_, _, body_width, body_height, area = stats[1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])]
	if area < width * height * 0.08 or body_height < height * 0.3:
		return None
	return body_width / body_height


def _retains_body_proportions(source_image, generated):
	source = _silhouette_aspect(source_image)
	result = _silhouette_aspect(generated)
	if source is None or result is None:
		return None
	# A change of view or upright pose can narrow the outline, but the generated
	# body must retain substantial width relative to the original rounded body.
	return result >= source * 0.65


def _visible_change(source_image, generated):
	"""Reject an unchanged source frame mislabeled as a new pose by vision."""
	import cv2
	import numpy as np

	def pixels(value):
		if isinstance(value, bytes):
			return cv2.imdecode(np.frombuffer(value, dtype=np.uint8), cv2.IMREAD_COLOR)
		path = (
			frappe.get_doc("File", {"file_url": value}).get_full_path()
			if value.startswith(("/private/files/", "/files/"))
			else value
		)
		return cv2.imread(str(path))

	before, after = pixels(source_image), pixels(generated)
	if before is None or after is None:
		return None
	before = cv2.resize(before, (128, 128), interpolation=cv2.INTER_AREA)
	after = cv2.resize(after, (128, 128), interpolation=cv2.INTER_AREA)
	return float(np.mean(np.abs(before.astype(np.float32) - after.astype(np.float32))) / 255) >= 0.05


def _clean_identity_source(project, source):
	"""Prefer a supplied, prop-free view of this identity for a reusable pose."""
	from joymedia.services.review.consistency import ask

	identity = source.get("identity_key")
	original_url = frappe.db.get_value("Asset Version", source.get("asset_version"), "file")
	candidates = [source] + [
		row
		for row in project.get("selected_media") or []
		if row.get("asset_version") != source.get("asset_version")
		and identity
		and row.get("identity_key") == identity
		and str(row.get("reference_role") or "").casefold() in {"character", "person"}
	]
	for candidate in candidates:
		file_url = frappe.db.get_value("Asset Version", candidate.get("asset_version"), "file")
		if not file_url:
			continue
		if (
			original_url
			and file_url != original_url
			and _retains_body_proportions(original_url, file_url) is False
		):
			continue
		answer = ask(file_url, HELD_PROP_QUESTION, max_edge=768).get("held_object_count")
		if type(answer) is int and answer == 0:
			return candidate, file_url
	# A held prop is acceptable as *input* to the pose generator when the user
	# supplied no clean photo. The generated asset is still required to pass
	# _accept_pose_view's independent no-prop check before it can be reused.
	if original_url:
		return source, original_url
	raise ValueError("No usable identity view is available for reusable pose generation.")


def _observed_pose_matches(content, pose_description, angle=None):
	from joymedia.services.planning.production import _ask_planner
	from joymedia.services.review.consistency import ask

	# Keep the target OUT of the vision question. When the target was included,
	# vision repeated "kneeling" for a visibly seated Shera and falsely accepted it.
	cache_key = None
	if isinstance(content, str):
		cache_key = "joymedia_pose_observed:" + hashlib.sha256(content.encode()).hexdigest()
	observed = frappe.cache.get_value(cache_key) if cache_key else None
	if observed is None:
		observed = ask(
			content,
			"Without knowing the intended pose, describe only the body pose and support visible "
			"in this image. Do not infer hidden knee, shin, foot or floor contacts. "
			"Distinguish resting on the rump with feet forward from kneeling on knees. "
			"Also describe camera view as front, side or back. "
			"Return JSON pose_description, visible_contact_points array, view, and certainty "
			"(high, medium, low).",
			max_edge=768,
		)
		if cache_key and observed.get("certainty") == "high":
			frappe.cache.set_value(cache_key, observed, expires_in_sec=7 * 24 * 3600)
	if observed.get("certainty") != "high" or not observed.get("pose_description"):
		return False
	match = _ask_planner(
		"Observed visible body state: "
		+ json.dumps(observed, ensure_ascii=False)
		+ "\nRequired body state: "
		+ pose_description
		+ ("\nRequired camera view: " + angle if angle else "")
		+ "\nAre all distinctive pose and weight-support requirements visibly the same? "
		"If a camera view is required, it must match too. Do not infer hidden contact points. "
		"Return JSON answer boolean and reason.",
		system="You compare an independently observed body pose to a required pose for exact physical match.",
		response_schema={
			"type": "object",
			"properties": {"answer": {"type": "boolean"}, "reason": {"type": "string"}},
			"required": ["answer", "reason"],
			"additionalProperties": False,
		},
	)
	return match.get("answer") is True


def _accept_pose_view(
	content, source_image=None, pose_description="standing on its own visible feet", angle=None
):
	from joymedia.services.review.consistency import ask

	if source_image is not None and _retains_body_proportions(source_image, content) is False:
		return False
	if source_image is not None and _visible_change(source_image, content) is False:
		return False
	# A target-led yes/no question can agree with the requested gesture even when
	# independent observation sees a different one.  Never let it override a
	# failed blind observation when certifying a reusable pose.
	if not _observed_pose_matches(content, pose_description, angle):
		return False
	support = ask(
		content,
		"Does this image contain exactly one complete character with connected anatomy, "
		"clear visible weight support and no furniture or product intersecting the body? "
		"Return JSON answer true only if unambiguous, false if wrong, null if uncertain, "
		"with reason.",
		max_edge=768,
	)
	# A combined question said answer=true for a real image even while its
	# reason acknowledged Shera was holding a pink heart. Check props alone.
	prop = ask(content, HELD_PROP_QUESTION, max_edge=768)
	count = prop.get("held_object_count")
	if support.get("answer") is not True or type(count) is not int or count != 0:
		return False
	# The broad support question accepted a real H3 side view whose lower body
	# had collapsed into one stump. Ask about that failure independently; a
	# separate foot count is unreliable for a stylized bear (toes look like feet).
	lower_body = ask(
		content,
		"Describe the lower body and floor contacts only. Count anatomically distinct "
		"legs and feet that are visible, and say if feet are fused into the body. "
		"Return JSON visible_leg_count integer, visible_foot_count integer, "
		"fused_lower_body boolean, reason string.",
		max_edge=768,
	)
	if lower_body.get("fused_lower_body") is not False:
		return False
	if source_image is None:
		return True
	identity = ask(
		[source_image, content],
		"Image 1 is the source character; image 2 is a generated pose. Ignoring pose, camera angle, "
		"lighting, plain background and removable held objects, does image 2 preserve the same "
		"character identity: body proportions and silhouette, face, colour, material and head-worn accessories? "
		"The source may be seated, but a rounded, squat bear with short paws and feet must not "
		"become a slender human-shaped bear with a narrow waist, long arms, long legs or fingers. "
		"Return JSON answer true only if recognizably the same character, false if different, "
		"or null if uncertain; include a reason.",
		max_edge=768,
	)
	if identity.get("answer") is not True:
		return False
	# Broad identity comparisons missed a new yellow flower on Shera. Check the
	# source and candidate independently before certifying a reusable pose.
	source_head = ask(source_image, HEAD_ACCESSORY_QUESTION, max_edge=768).get("head_accessories")
	generated_head = ask(content, HEAD_ACCESSORY_QUESTION, max_edge=768).get("head_accessories")
	if not isinstance(source_head, list) or not isinstance(generated_head, list):
		return False
	if sorted(str(item).strip().casefold() for item in source_head) != sorted(
		str(item).strip().casefold() for item in generated_head
	):
		return False
	# A broad identity judgement can miss a small but defining facial mark.
	# Ask each image independently: paired-image comparisons have repeatedly
	# described this Shera source's closed eyes as open in both pictures.
	if angle == "front":
		source_eyes = ask(source_image, EYE_DESIGN_QUESTION, max_edge=768).get("eye_shape")
		generated_eyes = ask(content, EYE_DESIGN_QUESTION, max_edge=768).get("eye_shape")
		if source_eyes in {"closed_arcs", "open_dots", "open_other", "closed_other"}:
			if generated_eyes != source_eyes:
				return False
	return True


def _target_pose_matches(content, pose_description, angle):
	"""Second observation path when a free-form pose caption is contradictory.

	The local vision model called a visibly standing Shera both "standing" and
	"resting on its rump" in the same answer. A narrow visual question recovers
	the support evidence without treating a generated caption as ground truth.
	"""
	from joymedia.services.review.consistency import ask

	view = f" from a {angle} view" if angle else ""
	answer = ask(
		content,
		f"Does this image visibly show this exact character body state{view}: {pose_description}? "
		"Judge visible limb articulation, contact with the floor and camera view. "
		"Answer false if any distinctive requirement is absent, and null if hidden "
		"or uncertain. Return JSON answer true, false or null and a reason.",
		max_edge=768,
	)
	return answer.get("answer") is True


def _h3_start_view(project, source, target_pose, angle, exclude_asset_versions=()):
	"""Choose the closest accepted pose of this identity as the motion source."""
	from joymedia.services.planning.production import _ask_planner

	clean, clean_url = _clean_identity_source(project, source)
	choices = (
		[]
		if clean.asset_version in exclude_asset_versions
		else [{"asset_version": clean.asset_version, "pose": "source view", "view": "source view"}]
	)
	urls = {clean.asset_version: clean_url} if choices else {}
	for row in project.get("selected_media") or []:
		if (
			row.asset_version == clean.asset_version
			or row.asset_version in exclude_asset_versions
			or row.identity_key != source.identity_key
		):
			continue
		if str(row.reference_role or "").casefold() not in {"character", "person"}:
			continue
		version = frappe.db.get_value(
			"Asset Version", row.asset_version, ["file", "analysis_status", "analysis_json"], as_dict=True
		)
		if not version or version.analysis_status != "Ready" or not version.file:
			continue
		analysis = frappe.parse_json(version.analysis_json or "{}")
		qualified = _qualified_pose_metadata(analysis)
		if not qualified:
			continue
		if _retains_body_proportions(clean_url, version.file) is False:
			continue
		choices.append(
			{"asset_version": row.asset_version, "pose": qualified["pose"], "view": qualified["view"]}
		)
		urls[row.asset_version] = version.file
	if not choices:
		return clean, clean_url
	if len(choices) == 1:
		row = next(row for row in project.selected_media if row.asset_version == choices[0]["asset_version"])
		return row, urls[row.asset_version]
	try:
		result = _ask_planner(
			"Choose the already accepted character view needing the smallest BODY POSE "
			"and camera-view change to reach the target. Prefer matching weight support "
			"over matching incidental paw gesture. Return only an asset_version from choices. "
			+ json.dumps({"target_pose": target_pose, "target_view": angle, "choices": choices}),
			system="You select an existing pose as a starting frame for a short animation.",
			response_schema={
				"type": "object",
				"properties": {"asset_version": {"type": "string"}},
				"required": ["asset_version"],
				"additionalProperties": False,
			},
		)
		selected = result.get("asset_version")
	except Exception:
		selected = None
	if selected in urls:
		row = next(row for row in project.selected_media if row.asset_version == selected)
		return row, urls[selected]
	row = next(row for row in project.selected_media if row.asset_version == choices[0]["asset_version"])
	return row, urls[row.asset_version]


def _pose_view_from_h3(project, source, pose_description, angle):
	"""Use the installed MiniMax H3 image-to-video workflow as a pose bridge.

	A real Shera pilot retained the mascot's squat silhouette for upright, side
	and raised-paw states where the human-skeleton Klein pose LoRA failed. Only
	independently accepted still frames can become reusable Character media.
	"""
	from PIL import Image

	from joymedia.services.workflows.comfyui import run_workflow_to_bytes, upload_frappe_file
	from joymedia.services.workflows.resolver import build_execution_workflow
	from joymedia.workflow_adapters import get_workflow_adapter

	name = frappe.conf.get("joymedia_pose_video_workflow")
	if not name:
		matches = frappe.get_all(
			"Generation Workflow",
			filters={"workflow_key": "minimax_h3_i2v"},
			pluck="name",
			order_by="creation desc",
			limit=1,
		)
		name = matches[0] if matches else None
	if not name:
		raise ValueError("No installed MiniMax H3 image-to-video workflow is available for pose preparation.")
	workflow = frappe.get_doc("Generation Workflow", name)
	angle_text = {"side": "side profile", "back": "rear view", "front": "front view"}[angle]
	prompt = (
		"One continuous studio shot of exactly the character in the first frame. "
		"It smoothly changes from its current pose into this final body state: "
		f"{pose_description}. End in a clear {angle_text} and hold the final pose. "
		"Preserve the same face, colour, material, proportions, head accessories; "
		"never add a flower, bow, hat or other head accessory absent in the source. "
		+ _eye_design_instruction(frappe.db.get_value("Asset Version", source.asset_version, "file"), angle)
		+ "rounded body and short limbs throughout. The character keeps connected "
		"anatomy and visible weight support on the floor. No human anatomy, long "
		"limbs, fingers, props, other characters, furniture, text or scene change. "
		"Plain neutral studio background, full body, fixed camera."
	)
	output = get_workflow_adapter(workflow).extract_execution_metadata(json.loads(workflow.workflow_json))[
		"primary_output_node_key"
	]
	tried_sources = set()
	for attempt in range(2):
		identity_source, file_url = _h3_start_view(
			project, source, pose_description, angle, exclude_asset_versions=tried_sources
		)
		tried_sources.add(identity_source.asset_version)
		path = frappe.get_doc("File", {"file_url": file_url}).get_full_path()
		with Image.open(path) as original:
			width, height = original.size
		# The pose library needs identity and silhouette detail, not final-video resolution.
		scale = 640 / max(width, height)
		width = max(320, round(width * scale / 32) * 32)
		height = max(320, round(height * scale / 32) * 32)
		frappe.db.commit()
		first_frame = upload_frappe_file(file_url)["server_path"]
		frame_count = 73
		graph = build_execution_workflow(
			workflow,
			inputs={"first_frame": [first_frame], "generation_prompt": prompt},
			seed=int(
				hashlib.sha256(
					f"{identity_source.asset_version}:{pose_description}:{angle}:{attempt}".encode()
				).hexdigest()[:12],
				16,
			),
			width=width,
			height=height,
			fps=float(workflow.output_fps or 24),
			frame_count=frame_count,
			output_prefix=f"joymedia/poses/{frappe.generate_hash(length=10)}",
		)
		video = run_workflow_to_bytes(graph, output, forget=True)
		with tempfile.TemporaryDirectory(prefix="joymedia-h3-pose-") as temp_dir:
			video_path = Path(temp_dir) / "pose.mp4"
			video_path.write_bytes(video)
			# The requested pose can appear before the end and then drift. Inspect a
			# bounded sequence through the transition, late frames first, using the
			# actual requested clip length rather than fixed timestamps.
			duration = max(0.1, (frame_count - 1) / float(workflow.output_fps or 24))
			for fraction in (0.95, 0.82, 0.69, 0.56, 0.43, 0.30):
				second = round(duration * fraction, 3)
				frame_path = Path(temp_dir) / "candidate.png"
				frame_path.unlink(missing_ok=True)
				result = subprocess.run(
					[
						"ffmpeg",
						"-hide_banner",
						"-loglevel",
						"error",
						"-y",
						"-ss",
						str(second),
						"-i",
						str(video_path),
						"-frames:v",
						"1",
						str(frame_path),
					],
					capture_output=True,
					timeout=60,
				)
				if result.returncode or not frame_path.exists():
					continue
				content = frame_path.read_bytes()
				try:
					if _accept_pose_view(content, file_url, pose_description, angle):
						return content
				except Exception:
					frappe.log_error(title="H3 pose observation unavailable; candidate not accepted")
	raise ValueError(f"H3 did not produce a qualified pose view: {pose_description}")


def _pose_view(project, source, pose_description, angle):
	if not frappe.conf.get("joymedia_pose_workflow"):
		try:
			return _pose_view_from_h3(project, source, pose_description, angle)
		except ValueError:
			# A failed video bridge is not evidence that the still-image identity
			# workflow cannot supply a pose. Both paths use the same admission check.
			frappe.log_error(title=f"H3 pose bridge deferred; trying still workflow for {project.name}")
	from joymedia.services.keyframes.locations import _keyframe_workflow
	from joymedia.services.planning.pose_guides import render_pose_guide
	from joymedia.services.project.context import _project_settings
	from joymedia.services.project.formats import preparation_dimensions
	from joymedia.services.workflows.comfyui import (
		run_workflow_to_bytes,
		upload_frappe_file,
		upload_local_file,
	)
	from joymedia.services.workflows.resolver import build_execution_workflow, get_workflow_input_contract
	from joymedia.workflow_adapters import get_workflow_adapter

	pose_workflow_name = frappe.conf.get("joymedia_pose_workflow")
	workflow = (
		frappe.get_doc("Generation Workflow", pose_workflow_name)
		if pose_workflow_name
		else _keyframe_workflow(project)
	)
	if not any(row["role"] == "character" for row in get_workflow_input_contract(workflow)):
		raise ValueError("The selected image workflow cannot take a character identity reference.")
	if pose_workflow_name and not any(
		row["role"] == "pose_guide" for row in get_workflow_input_contract(workflow)
	):
		raise ValueError("The configured pose workflow lacks a required pose guide input.")
	identity_source, file_url = _clean_identity_source(project, source)
	frappe.db.commit()  # The remote GPU call should not hold a project write transaction.
	image = upload_frappe_file(file_url)["server_path"]
	width, height = preparation_dimensions(_project_settings(project))
	pose_guide = None
	if pose_workflow_name:
		with tempfile.TemporaryDirectory(prefix="joymedia-pose-guide-") as temp_dir:
			guide_path = render_pose_guide(pose_description, angle, width, height, f"{temp_dir}/guide.png")
			pose_guide = upload_local_file(guide_path)["server_path"]
	angle_text = {"side": "side profile", "back": "rear three-quarter", "front": "front three-quarter"}[angle]
	prompt = (
		("refcontrol. Follow image 1 for body articulation and image 2 for identity. " if pose_guide else "")
		+ "One full-body character pose reference on a plain neutral studio ground. "
		"Render exactly the same character as the supplied identity image: preserve face, anatomy, "
		+ _eye_design_instruction(file_url, angle)
		+ "colour, material, markings and wearable accessories. The source may show a separate held prop: "
		"remove every object held in the paws or arms. A held heart, toy, tool or package is not part of "
		"the character's body or costume. Keep only head accessories present in the source; "
		"never add a flower, bow, hat or other accessory absent in the source. "
		f"Required body pose: {pose_description}. Camera view: {angle_text}. "
		"The entire body and its weight-bearing contact points are in frame on one continuous floor plane. "
		"Keep limbs separate and physically attached. No furniture, table, product, other character, "
		"human limbs, held object, inset panel or text. Natural contact shadow."
	)
	stored = json.loads(workflow.workflow_json)
	output = get_workflow_adapter(workflow).extract_execution_metadata(stored)["primary_output_node_key"]
	for attempt in range(2):
		seed = int(
			hashlib.sha256(
				f"{identity_source.get('asset_version')}:{pose_description}:{angle}:{attempt}".encode()
			).hexdigest()[:12],
			16,
		)
		inputs = {"generation_prompt": prompt, "character": [image]}
		if pose_guide:
			inputs["pose_guide"] = [pose_guide]
		graph = build_execution_workflow(
			workflow,
			inputs=inputs,
			seed=seed,
			width=width,
			height=height,
			fps=float(workflow.output_fps or 24),
			frame_count=1,
			output_prefix=f"joymedia/poses/{frappe.generate_hash(length=10)}",
		)
		content = run_workflow_to_bytes(graph, output, forget=True)
		try:
			if not _accept_pose_view(content, file_url, pose_description, angle):
				continue
		except Exception:
			frappe.log_error(title="Pose view observation unavailable; reusable pose not accepted")
			continue
		return content
	raise ValueError(f"No generated pose passed support and identity review: {pose_description}")


def _plan_required_states(script, selected):
	"""Ask the existing planner for the finite opening states needed by the full script.

	This is a planning decision, not a keyword classification of verbs. Object grip,
	pack position and background remain scene-specific storyboard responsibilities.
	"""
	from joymedia.services.planning.production import _ask_planner

	characters = {
		row.get("reference_key"): row.get("identity_key")
		for row in selected
		if str(row.get("reference_role") or "").casefold() in {"character", "person"}
	}
	available_views = []
	for row in selected:
		if str(row.get("reference_role") or "").casefold() not in {"character", "person"}:
			continue
		try:
			analysis = (
				frappe.parse_json(
					frappe.db.get_value("Asset Version", row.get("asset_version"), "analysis_json") or "{}"
				)
				or {}
			)
		except Exception:
			analysis = {}
		# Only a promoted generated pose has passed the prop, support, identity and
		# body-shape checks.  The original upload can still be useful as an identity
		# anchor, but must not be presented to the Director as a reliable action view.
		qualified = _qualified_pose_metadata(analysis)
		if qualified:
			available_views.append(
				{
					"key": row.get("reference_key"),
					"identity": row.get("identity_key"),
					"pose": qualified["pose"][:180],
					"view": qualified["view"],
				}
			)
	scenes = [
		{
			"scene_index": i,
			"cast": [key for key in scene.get("cast") or [] if key in characters],
			"action": scene.get("action"),
			"start_state": scene.get("start_state"),
			"subject_motion": scene.get("subject_motion"),
			"visual_camera": scene.get("visual_camera"),
			"image_prompt": scene.get("image_prompt"),
		}
		for i, scene in enumerate(script.get("scenes") or [])
	]
	if not any(scene["cast"] for scene in scenes):
		return []
	schema = {
		"type": "object",
		"properties": {
			"states": {
				"type": "array",
				"items": {
					"type": "object",
					"properties": {
						"scene_index": {"type": "integer"},
						"cast_key": {"type": "string"},
						"reference_key": {"type": "string"},
						"opening_pose": {"type": "string"},
						"view": {"type": "string", "enum": ["front", "side", "back"]},
					},
					"required": ["scene_index", "cast_key", "reference_key", "opening_pose", "view"],
					"additionalProperties": False,
				},
			}
		},
		"required": ["states"],
		"additionalProperties": False,
	}
	prompt = (
		"Read ALL scenes before planning. Return one state for every (scene_index, cast_key) pair, "
		"with no extras. Describe the character's OPENING body pose and visible weight support "
		"in one concise English sentence, including limb placement and orientation. The supplied "
		"photo is an identity anchor, not a restriction on poses or actions. Infer the first "
		"state from the explicit start_state when present, otherwise the earliest timed "
		"action and continuity from preceding scenes. "
		"If available_views contains a same-identity qualified view that can begin the opening action, "
		"return its exact key as reference_key and copy its exact pose text and view. "
		"For example, a stand-up action opens in a seated qualified view; an already-walking "
		"shot opens in a standing qualified view. If none can begin the action, set reference_key "
		"to cast_key and describe the missing body state. Preserve action-defining gestures "
		"such as a raised paw for a wave, even when the body remains standing. "
		"Preserve each action-defining limb gesture in the OPENING state, including "
		"a paw reaching toward, steadying, lifting from or presenting an object. "
		"Describe the visible shoulder, elbow and paw positions without drawing the "
		"object itself. A neutral standing pose does not satisfy a scripted reach, "
		"two-paw manipulation or raised-paw presentation. Omit only incidental facial "
		"expression and finger detail. Keep separately held "
		"props, products, furniture, backgrounds and text OUT of reusable character poses. "
		"The next stage will check whether an existing image shows that pose and view. "
		"Never invent extra limbs or unsupported body contact. Never use hold, holding, "
		"carrying, gripping, clutching or presenting in opening_pose: translate those "
		"actions into precise prop-free limb articulation instead. "
		"If the shot involves a product, "
		"the storyboard later composes the contact; describe only the reusable body pose. "
		+ json.dumps(
			{"characters": characters, "available_views": available_views, "scenes": scenes},
			ensure_ascii=False,
		)
	)
	result = _ask_planner(
		prompt,
		system="You plan reusable character pose references for a film.",
		capability="planner",
		sampling_profile="production_plan",
		response_schema=schema,
	)
	states = result.get("states") if isinstance(result, dict) else None
	expected = {(scene["scene_index"], key) for scene in scenes for key in scene["cast"]}
	if not isinstance(states, list):
		raise ValueError("Pose planner did not cover every character in the script.")

	def normalize_states(rows):
		"""Map a unique identity alias to its cast key and collapse duplicates.

		The planner can return both the identity name and the exact media key for
		the same character.  That is one state, not an omitted scene or a second
		actor; prefer the exact cast-key response when both are present.
		"""
		by_pair = {}
		invalid = []
		for row in rows:
			if not isinstance(row, dict):
				invalid.append(row)
				continue
			index, key = row.get("scene_index"), row.get("cast_key")
			pair = (index, key)
			exact = pair in expected
			if not exact:
				aliases = [
					cast
					for scene_index, cast in expected
					if scene_index == index
					and characters.get(cast)
					and (characters.get(cast) == key or characters.get(cast) == characters.get(key))
				]
				if len(aliases) == 1:
					row = {**row, "cast_key": aliases[0]}
					pair = (index, aliases[0])
			if pair not in expected:
				invalid.append(row)
			elif pair not in by_pair or (exact and not by_pair[pair][1]):
				by_pair[pair] = (row, exact)
		return [state for state, _ in by_pair.values()] + invalid

	states = normalize_states(states)
	# Long scripts can produce a valid but truncated structured response. Ask once
	# for only the omitted pairs, with the complete script still available for
	# continuity. Never invent a body state just to let rendering proceed.
	returned = {(row.get("scene_index"), row.get("cast_key")) for row in states if isinstance(row, dict)}
	missing = expected - returned
	if missing:
		completion = _ask_planner(
			prompt
			+ "\nComplete ONLY these omitted (scene_index, cast_key) pairs: "
			+ json.dumps(sorted(missing), ensure_ascii=False)
			+ ". Return no other pairs in states.",
			system="You complete missing reusable character pose states for a film.",
			capability="planner",
			sampling_profile="production_plan",
			response_schema=schema,
		)
		extra = completion.get("states") if isinstance(completion, dict) else None
		if isinstance(extra, list):
			states = normalize_states([*states, *extra])
	if len(states) != len(expected):
		raise ValueError("Pose planner did not cover every character in the script.")
	states.sort(key=lambda state: state.get("scene_index") if type(state.get("scene_index")) is int else -1)
	seen = set()
	previous_by_identity = {}
	for state in states:
		# Compatibility for an in-flight or cached planner response produced before
		# reference_key was added.  New responses must make the choice explicitly.
		if not state.get("reference_key"):
			state["reference_key"] = state.get("cast_key")
		pair = (state.get("scene_index"), state.get("cast_key"))
		if pair not in expected and type(state.get("scene_index")) is int:
			# The planner sometimes substitutes another view of the same identity
			# for a script cast key. The required state still belongs to the exact
			# cast entry in that scene; normalize only an unambiguous identity match.
			aliases = [
				key
				for index, key in expected
				if index == state["scene_index"]
				and characters.get(key)
				and characters.get(key) == characters.get(state.get("cast_key"))
				and (index, key) not in seen
			]
			if len(aliases) == 1:
				state["cast_key"] = aliases[0]
				pair = (state["scene_index"], aliases[0])
		if (
			pair not in expected
			or pair in seen
			or not str(state.get("reference_key") or "").strip()
			or not str(state.get("opening_pose") or "").strip()
			or state.get("view") not in {"front", "side", "back"}
		):
			raise ValueError("Pose planner returned an invalid or duplicate scene state.")
		# A view is reusable only within its own identity.  The key is deliberately
		# explicit so a qualified standing or side view is selected before the image
		# service is ever asked to invent a pose.
		candidate = next(
			(row for row in selected if row.get("reference_key") == state["reference_key"]), None
		)
		if candidate and candidate.get("identity_key") != characters.get(state["cast_key"]):
			raise ValueError("Pose planner selected a view from another identity.")
		# The script, rather than a source image or a probabilistic pose-choice
		# response, defines which body support may open a shot.  In particular, an
		# already-moving character cannot open from a seated reference unless the
		# written action explicitly starts by standing up.  Select qualified media
		# that meets the requirement before the image stage is allowed to run.
		from joymedia.services.planning.pose_coverage import required_pose

		script_scene = script["scenes"][state["scene_index"]]
		requirement = required_pose(
			script_scene.get("action"),
			{"subject_motion": script_scene.get("subject_motion")},
		)
		if requirement == "preserve_reference_pose":
			# A prop interaction alone does not move the body from seated to
			# standing. An explicit opening composition can do so; otherwise
			# preserve the preceding script state for this same character.
			requirement = required_pose(
				" ".join(str(script_scene.get(field) or "") for field in ("image_prompt", "visual_camera"))
			)
		if (
			requirement == "preserve_reference_pose"
			and characters.get(state["cast_key"]) in previous_by_identity
		):
			previous = previous_by_identity[characters[state["cast_key"]]]
			# Preserve weight support, but retain a new visible gesture from the
			# planner. An object interaction must not silently erase a wave or turn.
			from joymedia.services.planning.pose_coverage import source_pose_state

			if source_pose_state([state["opening_pose"]]) != source_pose_state([previous["opening_pose"]]):
				state.update({key: previous[key] for key in ("reference_key", "opening_pose", "view")})
				candidate = next(
					(row for row in selected if row.get("reference_key") == state["reference_key"]), None
				)
		qualified = None
		if candidate:
			candidate_analysis = (
				frappe.parse_json(
					frappe.db.get_value("Asset Version", candidate.get("asset_version"), "analysis_json")
					or "{}"
				)
				or {}
			)
			qualified = _qualified_pose_metadata(candidate_analysis)
		needed_support = {
			"upright_supported": "mobile_or_upright",
			"seated_supported": "seated_supported",
		}.get(requirement)
		from joymedia.services.planning.pose_coverage import source_pose_state

		requested_pose = " ".join(state["opening_pose"].strip().casefold().split())
		qualified_pose = " ".join(qualified["pose"].strip().casefold().split()) if qualified else ""
		selected_matches = bool(
			qualified
			and (not needed_support or source_pose_state([qualified["pose"]]) == needed_support)
			and (requested_pose == qualified_pose or requested_pose in qualified_pose)
			and state["view"] == qualified["view"]
		)
		# A wrong support state needs correction, but an already suitable
		# state may contain a meaningful limb gesture. Never replace that
		# gesture with the first standing or seated asset in the list.
		planner_support = source_pose_state([state["opening_pose"]])
		needs_support_correction = bool(needed_support and planner_support != needed_support)
		compatible, compatible_pose = (None, None)
		if needs_support_correction:
			compatible, compatible_pose = _qualified_view_for_requirement(
				selected, characters.get(state["cast_key"]), requirement, state["view"]
			)
		if selected_matches:
			state["opening_pose"] = qualified["pose"]
		elif compatible:
			candidate = compatible
			state["reference_key"] = compatible.get("reference_key")
			state["opening_pose"] = compatible_pose["pose"]
			state["view"] = compatible_pose.get("view") or state["view"]
		elif needs_support_correction:
			# The opening state is authored by the script. A planner that describes
			# the later action as the first frame must not change that state merely
			# because no matching reference is already in the library.
			repaired = _ask_planner(
				"Describe only the character's OPENING body pose for this scene. "
				"Keep the body support required by the first action and explicit start_state; "
				"omit all props, products and scenery. Do not describe a later action as "
				"the opening pose. Return JSON pose string. "
				+ json.dumps(
					{
						"start_state": script_scene.get("start_state"),
						"action": script_scene.get("action"),
						"required_support": requirement,
						"rejected_pose": state["opening_pose"],
					},
					ensure_ascii=False,
				),
				system="You correct a first-frame pose to match the authored scene opening.",
				capability="planner",
				sampling_profile="production_plan",
				response_schema={
					"type": "object",
					"properties": {"pose": {"type": "string"}},
					"required": ["pose"],
					"additionalProperties": False,
				},
			)
			corrected = str(repaired.get("pose") or "").strip()
			if source_pose_state([corrected]) != needed_support:
				raise ValueError("Pose planner could not preserve the scripted opening body support.")
			state["opening_pose"] = corrected[:300]
			state["reference_key"] = state["cast_key"]
		elif requirement == "upright_supported" or qualified:
			# No reviewed upright view exists.  Keep the canonical identity as the
			# source so preparation creates the requested pose and view.
			candidate = next(
				(row for row in selected if row.get("reference_key") == state["cast_key"]),
				None,
			)
			state["reference_key"] = state["cast_key"]
		# A qualified view is the durable evidence for its body state.  The planner
		# chooses *which* view opens a scene; it must not be able to corrupt that
		# contract by paraphrasing the later product interaction into its pose text.
		# This also makes cached/planner answers harmless when they mention a pack
		# even though the selected standing or seated Character image is correct.
		if candidate and selected_matches:
			candidate_analysis = (
				frappe.parse_json(
					frappe.db.get_value("Asset Version", candidate.get("asset_version"), "analysis_json")
					or "{}"
				)
				or {}
			)
			qualified = _qualified_pose_metadata(candidate_analysis)
			if qualified:
				state["opening_pose"] = qualified["pose"]
				state["view"] = qualified["view"] or state["view"]
		if re.search(
			r"\b(?:hold|holding|carry|carrying|grip|gripping|clutch|clutching|presenting)\b",
			str(state["opening_pose"]),
			re.I,
		):
			# The planner occasionally repeats a scripted prop verb despite the
			# prop-free contract. Preserve the requested limb geometry while
			# removing only the object/contact description; do not collapse the
			# action back to a neutral standing pose.
			candidate_pose = str(state["opening_pose"])
			for _ in range(2):
				repaired = _ask_planner(
					"Rewrite this reusable character pose without objects, products, furniture, "
					"contact verbs, or phrases like 'as if holding something'. Preserve its "
					"body support, view, and the spatial position of EVERY paw and arm. "
					"Describe only visible body articulation; do not invent limbs. "
					"Return JSON pose string. Source: " + candidate_pose,
					system="You preserve a character pose while removing scene props.",
					capability="planner",
					sampling_profile="production_plan",
					response_schema={
						"type": "object",
						"properties": {"pose": {"type": "string"}},
						"required": ["pose"],
						"additionalProperties": False,
					},
				)
				candidate_pose = str(repaired.get("pose") or "").strip() if isinstance(repaired, dict) else ""
				if candidate_pose and not re.search(
					r"\b(?:hold|holding|carry|carrying|grip|gripping|clutch|clutching|presenting)\b",
					candidate_pose,
					re.I,
				):
					break
			if not candidate_pose or re.search(
				r"\b(?:hold|holding|carry|carrying|grip|gripping|clutch|clutching|presenting)\b",
				candidate_pose,
				re.I,
			):
				raise ValueError("Reusable character pose includes scene-specific object contact.")
			state["opening_pose"] = candidate_pose[:300]
		if characters.get(state["cast_key"]):
			previous_by_identity[characters[state["cast_key"]]] = dict(state)
		seen.add(pair)
	return states


def _view_matches(file_url, pose_description, angle):
	"""A reusable action view must match the body state and have empty paws.

	A pose-only comparison can accept a seated source holding an unrelated prop
	for a seated, free-paw scene. Check object contact independently before the
	view can bypass automatic pose generation.
	"""
	from joymedia.services.review.consistency import ask

	if not _observed_pose_matches(file_url, pose_description, angle):
		return False
	count = ask(file_url, HELD_PROP_QUESTION, max_edge=768).get("held_object_count")
	return type(count) is int and count == 0


def prepare_script_pose_views(project, script, _retry_deferred=True):
	"""Resolve script-required character states before importing the storyboard."""
	from joymedia.services.project.reference_lineage import lineage_identity

	# Older imports could label a generated view as a new identity. Repair only
	# recorded source-lineage variants before planning, so a script cast can use
	# every qualified pose of that same subject without borrowing another cast.
	identity_repaired = False
	for row in project.get("selected_media") or []:
		if str(row.get("reference_role") or "").casefold() not in {"character", "person"}:
			continue
		canonical = lineage_identity(project, row)
		if canonical and row.get("identity_key") != canonical:
			row.identity_key = canonical
			identity_repaired = True
	if identity_repaired:
		project.save(ignore_permissions=True)
	selected = list(project.get("selected_media") or [])
	initial_view_count = len(selected)
	by_key = {str(row.get("reference_key") or ""): row for row in selected}
	# The storyboard must not start from an unknown body state.  Retry the planner
	# once, then return explicit deferred evidence for the batch gate instead of
	# silently falling back to the uploaded seated reference.
	for attempt in range(2):
		try:
			states = _plan_required_states(script, selected)
			break
		except Exception:
			frappe.log_error(title=f"Pose planner attempt {attempt + 1} deferred for {project.name}")
	else:
		return [
			{"scene": i + 1, "source": key, "status": "deferred", "reason": "pose plan unavailable"}
			for i, scene in enumerate(script.get("scenes") or [])
			for key in scene.get("cast") or []
			if key in by_key
		]
	prepared = []
	failed_pose_keys = set()
	for state in states:
		scene = script["scenes"][state["scene_index"]]
		cast_key = state["cast_key"]
		source = by_key[cast_key]
		try:
			source_analysis = (
				frappe.parse_json(
					frappe.db.get_value("Asset Version", source.asset_version, "analysis_json") or "{}"
				)
				or {}
			)
		except Exception:
			source_analysis = {}
		if source_analysis.get("source_asset_version") and not _qualified_pose_metadata(source_analysis):
			original = next(
				(
					row
					for row in selected
					if row.get("asset_version") == source_analysis["source_asset_version"]
				),
				None,
			)
			if original:
				source = original
		pose = " ".join(state["opening_pose"].split())[:300]
		angle = state["view"]
		identity = source.get("identity_key") or source.get("reference_key")
		key = "pose_" + hashlib.sha256(f"{identity}:{pose.casefold()}:{angle}".encode()).hexdigest()[:12]
		choice = by_key.get(key)
		if choice:
			try:
				choice_analysis = (
					frappe.parse_json(
						frappe.db.get_value("Asset Version", choice.asset_version, "analysis_json") or "{}"
					)
					or {}
				)
			except Exception:
				choice_analysis = {}
			if choice_analysis.get("source_asset_version") and not _qualified_pose_metadata(choice_analysis):
				choice = None
		preferred = by_key.get(state.get("reference_key"))
		if preferred and preferred.get("identity_key") == identity:
			try:
				analysis = (
					frappe.parse_json(
						frappe.db.get_value("Asset Version", preferred.asset_version, "analysis_json") or "{}"
					)
					or {}
				)
			except Exception:
				analysis = {}
			# This asset was already qualified when it entered Character media. Reusing
			# it avoids a second, target-led vision comparison and keeps the Director's
			# explicit opening-pose choice intact.
			qualified = _qualified_pose_metadata(analysis)
			if (
				qualified
				and " ".join(qualified["pose"].casefold().split()) == pose.casefold()
				and (not qualified["view"] or qualified["view"] == angle)
			):
				choice = preferred
		if not choice:
			# Source and alternate views are checked visually against the planned
			# state; text labels and action keywords cannot certify a pose.
			candidates = [source] + [
				row
				for row in selected
				if row is not source
				and source.get("identity_key")
				and row.get("identity_key") == source.get("identity_key")
				and str(row.get("reference_role") or "").casefold() in {"character", "person"}
			]
			for candidate in candidates:
				try:
					candidate_analysis = (
						frappe.parse_json(
							frappe.db.get_value("Asset Version", candidate.asset_version, "analysis_json")
							or "{}"
						)
						or {}
					)
				except Exception:
					candidate_analysis = {}
				if candidate_analysis.get("source_asset_version") and not _qualified_pose_metadata(
					candidate_analysis
				):
					continue
				url = frappe.db.get_value("Asset Version", candidate.asset_version, "file")
				try:
					matches = bool(url and _view_matches(url, pose, angle))
				except Exception:
					frappe.log_error(title=f"Pose view observation unavailable for {project.name}")
					matches = False
				if matches:
					choice = candidate
					break
		if not choice:
			if key in failed_pose_keys:
				prepared.append(
					{
						"scene": state["scene_index"] + 1,
						"source": cast_key,
						"pose": pose,
						"status": "deferred",
						"reason": "same pose failed qualification earlier in this pass",
					}
				)
				continue
			try:
				content = _pose_view(project, source, pose, angle)
				from joymedia.services.intake.subject_cutout import cutout_studio_reference, sam2_configured

				mask_evidence = None
				if sam2_configured():
					content, mask_evidence = cutout_studio_reference(content)
				frappe.db.commit()  # Do not hold a transaction across GPU rendering.
				from joymedia.services.intake.assets import create_media_asset

				image = frappe.get_doc(
					{
						"doctype": "File",
						"file_name": f"{key}.png",
						"content": content,
						"is_private": 1,
						"attached_to_doctype": "Media Project",
						"attached_to_name": project.name,
					}
				).insert(ignore_permissions=True)
				asset = create_media_asset(
					f"{source.label or cast_key} {pose[:60]} {angle}",
					"Character",
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
								"kind": "character",
								"description": f"Same character in {pose}; {angle} view",
								"pose_and_support": pose,
								"view": angle,
								"qualified_pose_and_support": pose,
								"qualified_pose_view": angle,
								"pose_qualification_version": POSE_QUALIFICATION_VERSION,
								"source_asset_version": source.asset_version,
								"subject_cutout": mask_evidence,
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
						"reference_key": key,
						"identity_key": source.identity_key,
						"reference_role": source.reference_role,
						"label": f"{source.label or cast_key} {pose[:60]} {angle} (generated)",
						# A source rule may describe its held prop or a particular shot.
						# The reusable pose must not carry that instruction into every scene.
						"relative_size": source.relative_size,
						"keep_rule": "",
					},
				)
				project.save(ignore_permissions=True)
				choice = project.selected_media[-1]
				selected.append(choice)
				by_key[key] = choice
			except Exception as exc:
				from joymedia.services.workflows.comfyui import ComfyJobLostError

				if isinstance(exc, ComfyJobLostError):
					raise
				failed_pose_keys.add(key)
				frappe.log_error(title=f"Pose preparation deferred for {project.name}")
				prepared.append(
					{
						"scene": state["scene_index"] + 1,
						"source": cast_key,
						"pose": pose,
						"status": "deferred",
					}
				)
				continue
		try:
			from joymedia.services.intake.subject_cutout import ensure_transparent_reference, sam2_configured

			if sam2_configured():
				choice = ensure_transparent_reference(project, choice)
		except Exception as exc:
			from joymedia.services.workflows.comfyui import ComfyJobLostError

			if isinstance(exc, ComfyJobLostError):
				raise
			frappe.log_error(title=f"Character cutout deferred for {project.name}")
			prepared.append(
				{
					"scene": state["scene_index"] + 1,
					"source": cast_key,
					"pose": pose,
					"status": "deferred",
					"reason": "exact-pixel character cutout unavailable",
				}
			)
			continue
		scene["cast"][scene["cast"].index(cast_key)] = choice.reference_key
		prepared.append(
			{
				"scene": state["scene_index"] + 1,
				"source": cast_key,
				"view": choice.reference_key,
				"pose": pose,
				"status": "ready",
			}
		)
	# Pose states can depend on each other: a side view may fail from the
	# supplied seated image, then succeed from a standing view prepared later
	# in this same script. Retry only after all first-pass states are available.
	# Bound the pass so a genuinely unsupported pose remains deferred.
	if (
		_retry_deferred
		and len(selected) > initial_view_count
		and any(row["status"] == "deferred" for row in prepared)
	):
		try:
			project.reload()
			retried = prepare_script_pose_views(project, script, _retry_deferred=False)
			by_scene = {(row["scene"], row["source"]): row for row in retried}
			for index, row in enumerate(prepared):
				if row["status"] == "deferred":
					candidate = by_scene.get((row["scene"], row["source"]))
					if candidate and candidate["status"] == "ready":
						prepared[index] = candidate
		except Exception as exc:
			from joymedia.services.workflows.comfyui import ComfyJobLostError

			if isinstance(exc, ComfyJobLostError):
				raise
			frappe.log_error(title=f"Pose retry pass deferred for {project.name}")
	return prepared
