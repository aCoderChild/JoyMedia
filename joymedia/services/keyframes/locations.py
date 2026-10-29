"""One picture of each place in the film, shared by every scene set there.

Each first frame was drawn on its own, so the same "warm family dining room" came out as a different room in every
scene. Now every place the storyboard names is drawn once, empty, before the first frames, and given to each scene that
shows the room as its Environment reference. The keyframe workflow's own Redux environment branch then draws those
scenes in that one room. This is the shared-anchor idea of Story2Board and ConsiStory, done with inputs the workflow
already has.

Redux carries the picture's layout along with its look (tried at strengths 0.5, 0.25 and 0.12: a close-up still came
out as the wide room), so a close-up or top-down scene gets a close view cut from the same picture (the middle of the
room around the table and floor): the same room, in a close composition. A scene with an Environment reference of its
own (a client's photo of the location) keeps it.
"""

import hashlib
import io
import json
import math
import re
from pathlib import Path

import frappe
from frappe import _
from PIL import Image

from joymedia.services.keyframes.overlay import usable_setting
from joymedia.services.project.realtime import PROJECT_UPDATED, publish_project_event

CLOSE_FRAMING = re.compile(r"close|top[- ]?down|overhead|bird'?s[- ]eye|insert|detail", re.I)
ROOM_FRAMING = re.compile(r"wide|medium|full|establishing|long shot", re.I)
LIVING_ROOM = re.compile(r"\bliving room\b|\bsitting room\b|\bfamily room\b|\blounge\b|phòng khách", re.I)


def _living_room_work_surface(setting, staging):
	"""A living-room action table must read as furniture belonging to that seating area."""
	return bool(LIVING_ROOM.search(str(setting or "")) and "working table" in str(staging or ""))


def location_key(setting):
	"""The project-reference key of a place's picture. Scenes with the same setting text share it."""
	place = " ".join(usable_setting(setting).casefold().split())
	return "location_" + hashlib.sha1(place.encode()).hexdigest()[:10]


def shows_the_room(shot):
	"""Whether the scene opens on a view of the room (wide, medium, or no framing given) rather than a close-up."""
	from joymedia.services.planning.prompts import opening_framing
	from joymedia.services.planning.shot_structure import structure_for

	structure = structure_for(shot)
	if structure:
		# A wide location anchor repeatedly pulled structured medium/detail shots
		# back to a full-room view. Keep their shared setting, with closer context.
		return structure["framing"] == "wide"

	framing = opening_framing(shot)
	return not CLOSE_FRAMING.search(framing) or bool(ROOM_FRAMING.search(framing))


def _location_versions(project, shots=()):
	"""The pictures the system may replace on these scenes: the drawn places, and any Environment picture a scene still
	has after a person removed it from the project's references."""
	current = {row.asset_version for row in project.selected_media or []}
	drawn = {
		row.asset_version
		for row in project.selected_media or []
		if (row.reference_key or "").startswith("location_")
	}
	stale = {
		row.asset_version
		for shot in shots
		for row in shot.generation_inputs or []
		if frappe.scrub(row.reference_role or "") == "environment" and row.asset_version not in current
	}
	return drawn | stale


def _own_environment(shot, places):
	"""Whether the scene has an Environment picture that is not one of the drawn places."""
	return any(
		frappe.scrub(row.reference_role or "") == "environment" and row.asset_version not in places
		for row in shot.generation_inputs or []
	)


def _single_authored_environment(project, shots):
	"""A sole supplied Environment anchors every scene without its own place.

	A writer may name the whole room in a wide shot and only its table in a
	close-up. Those are views of the client's one supplied place, not requests
	to invent two new rooms from slightly different text.
	"""
	choices = {
		row.asset_version
		for row in project.get("selected_media") or []
		if frappe.scrub(row.get("reference_role") or "") == "environment"
		and row.get("asset_version")
		and not str(row.get("reference_key") or "").startswith("location_")
	}
	return next(iter(choices)) if len(choices) == 1 else None


def shot_views(shot):
	"""A split-screen scene's views ([{"text", "source"}], top to bottom); empty for a full-frame scene."""
	try:
		return json.loads(shot.get("views_json") or "[]") or []
	except (TypeError, ValueError):
		return []


GENERIC_WORDS = {
	"with",
	"from",
	"into",
	"inside",
	"outside",
	"warm",
	"cozy",
	"cosy",
	"bright",
	"soft",
	"light",
	"natural",
	"there",
}


def same_place(view, setting):
	"""Whether a split-screen view is the film's own place ("Family dining table" in "a cozy family dining room with a
	wooden table"): two or more of its words in common."""

	def words(text):
		return set(re.findall(r"[a-z]{4,}", str(text or "").casefold())) - GENERIC_WORDS

	return len(words(view) & words(setting)) >= 2


def place_key(project, setting):
	"""The key of the picture of the place a setting describes. A setting worded differently from a place already drawn
	("Family dining room with warm light" after "Warm, cozy family dining room with a wooden table") is the same place:
	re-planning a scene must not give it a new room."""
	floor = _floor_location_required(project, setting)
	key = location_key(setting).replace("location_", "location_floor_", 1) if floor else location_key(setting)
	for row in project.get("selected_media") or []:
		known = row.reference_key or ""
		if known == key:
			return key
	place = usable_setting(setting)
	for row in project.get("selected_media") or []:
		known, label = row.reference_key or "", row.label or ""
		if (
			known.startswith("location_")
			and floor == known.startswith("location_floor_")
			and not known.endswith(CLOSE)
			and label.startswith("Location ")
			and same_place(place, label.split(":", 1)[-1])
		):
			return known
	return key


def _floor_location_required(project, setting):
	"""Keep generated floor-only action spaces separate from tabletop plates."""
	from joymedia.services.review.physical_audit import opening_actor_support

	try:
		source = frappe.parse_json(project.get("storyboard_source_json") or "{}") or {}
		scenes = (source.get("selected_demo") or {}).get("scenes") or []
		scenes = [s for s in scenes if same_place(str(s.get("place") or setting), setting)]
		opens = [str(s.get("camera") or s.get("visual_camera") or "") for s in scenes]
		text = " ".join(
			str(s.get(k) or "") for s in scenes for k in ("camera", "visual_camera", "action", "place")
		)
		return any(opening_actor_support(o) == "ground" for o in opens) and not re.search(
			r"\b(?:table|desk|counter|worktop)\b", text, re.I
		)
	except (TypeError, ValueError):
		return False


def view_key(project, view, setting):
	"""The picture a split-screen view is built on: the close view of the film's own room when the view is that place
	(so the panel matches the other scenes), else a picture of its own."""
	return f"{place_key(project, setting)}{CLOSE}" if same_place(view, setting) else place_key(project, view)


def missing_views(project, shots):
	"""{key: view} for each split-screen view, not the film's own place, that has no picture yet."""
	have = {row.reference_key for row in project.selected_media or []}
	missing = {}
	for shot in shots:
		for view in shot_views(shot):
			key = view_key(project, view["text"], shot.setting_prompt)
			if not key.endswith(CLOSE) and key not in have:
				missing.setdefault(key, view["text"])
	return missing


def missing_places(project, shots):
	"""{key: setting} for each place shown by these scenes that has no picture yet."""
	have = {row.reference_key for row in project.selected_media or []}
	places = _location_versions(project, shots)
	provided = _single_authored_environment(project, shots)
	missing = {}
	for shot in shots:
		key = place_key(project, shot.setting_prompt)
		if not provided and not _own_environment(shot, places) and key not in have:
			setting = usable_setting(shot.setting_prompt)
			# Match synonymous settings within this pending batch as well as places
			# already attached to the project. Otherwise "Same living room" gets
			# drawn as a second, inconsistent room before either plate is stored.
			if not any(same_place(setting, prior) for prior in missing.values()):
				missing.setdefault(key, setting)
	return missing


def assign_places(project, shots):
	"""Give each scene the picture of its place: the whole room, or the close view for a close-up. Returns how many
	scenes changed."""
	from joymedia.services.review.comments import _reseal_approved_plan
	from joymedia.services.workflows.capabilities import controls

	free_composition = bool(
		project.get("workflow")
		and "reference_only" in controls(frappe.get_doc("Generation Workflow", project.workflow))
	)
	if not free_composition and project.get("generation_pipeline"):
		from joymedia.services.workflows.pipeline import get_pipeline_steps

		image_stage = frappe.get_doc(
			"Generation Workflow", get_pipeline_steps(project.generation_pipeline)[0].workflow
		)
		free_composition = bool(
			image_stage.get("output_media_type") == "Image" and "free_composition" in controls(image_stage)
		)
	# A free-composition renderer receives setting identity, not a fixed opening
	# crop. The legacy centre crop can remove the actual support surface and
	# misleadingly condition a product onto furniture elsewhere in the room.
	if not free_composition:
		project = _ensure_close_views(project, shots)
	pictures = {
		row.reference_key: row.asset_version for row in project.selected_media or [] if row.reference_key
	}
	places = _location_versions(project, shots)
	provided = _single_authored_environment(project, shots)
	changed = 0
	for shot in shots:
		if _own_environment(shot, places):
			continue
		key = place_key(project, shot.setting_prompt)
		wanted = provided or pictures.get(
			key if free_composition or shows_the_room(shot) else f"{key}{CLOSE}"
		)
		current = [row for row in shot.generation_inputs or [] if row.asset_version in places]
		if [row.asset_version for row in current] == ([wanted] if wanted else []):
			continue
		# Changed as rows, not by saving the scene: another scene's render may be running, and its run already holds
		# its own copy of the storyboard.
		for row in current:
			frappe.db.delete("Shot Reference", {"name": row.name})
			shot.generation_inputs.remove(row)
		if wanted:
			shot.append(
				"generation_inputs", {"reference_role": "Environment", "asset_version": wanted}
			).db_insert()
		changed += 1
	if changed:
		# The pictures follow from the approved settings and framings, not an edit to the storyboard.
		_reseal_approved_plan(project.name)
	return changed


CLOSE = "_close"
# The part of a place picture a close-up is cut from: the middle of the room, where the table and the floor are.
CLOSE_VIEW = (0.2, 0.35, 0.8, 0.85)


def close_view(content):
	"""PNG bytes of the close view of a place picture, at the picture's own size."""
	import io

	from PIL import Image, ImageOps

	with Image.open(io.BytesIO(content)) as image:
		width, height = image.size
		left, top, right, bottom = CLOSE_VIEW
		crop = image.convert("RGB").crop(
			(int(left * width), int(top * height), int(right * width), int(bottom * height))
		)
		# Fill the frame's shape from the cut, keeping its middle.
		output = io.BytesIO()
		ImageOps.fit(crop, (width, height), method=Image.Resampling.LANCZOS).save(output, "PNG")
		return output.getvalue()


def _ensure_close_views(project, shots):
	"""Cut the close view of each place a close-up scene needs, from the place's picture; returns the project."""
	pictures = {row.reference_key: row for row in project.selected_media or [] if row.reference_key}
	added = False
	for shot in shots:
		key = place_key(project, shot.setting_prompt)
		needs_close = not shows_the_room(shot) or any(
			view_key(project, v["text"], shot.setting_prompt) == f"{key}{CLOSE}" for v in shot_views(shot)
		)
		if not needs_close or f"{key}{CLOSE}" in pictures or key not in pictures:
			continue
		file_url = frappe.db.get_value("Asset Version", pictures[key].asset_version, "file")
		content = frappe.get_doc("File", {"file_url": file_url}).get_content()
		label = (pictures[key].label or "Location").replace(":", " close-up:", 1)
		_store_place(project, f"{key}{CLOSE}", label, close_view(content))
		pictures[f"{key}{CLOSE}"] = True
		added = True
	return frappe.get_doc("Media Project", project.name) if added else project


def _keyframe_workflow(project=None):
	from joymedia.services.workflows.pipeline import (
		get_active_generation_pipeline,
		get_pinned_generation_pipeline,
		get_pipeline_steps,
	)

	name = project.get("name") if project else None
	pipeline = (get_pinned_generation_pipeline(name) if name else None) or get_active_generation_pipeline()
	steps = get_pipeline_steps(pipeline.name)
	workflow = frappe.get_doc("Generation Workflow", steps[0].workflow) if steps else None
	if not workflow or workflow.output_media_type != "Image":
		frappe.throw(_("The production pipeline has no image stage to draw the places with."))
	return workflow


VIEW_SETTING = (
	"A close view of this place, with a clear, empty spot in the middle where an object will stand. Natural light, "
	"realistic, warm and soft."
)

LOCATION_PLATE = (
	"Establish one complete furnished location in coherent perspective. Keep its architecture, floor, fixed "
	"furnishings and practical light consistent. Give the room foreground, middle-ground and background depth "
	"through its existing materials and lighting. When no illustrated medium is requested, render as naturalistic "
	"live-action commercial photography with believable textures, lens depth and motivated practical light; "
	"avoid drawn outlines or flat cartoon shading. Use setting-appropriate furniture, subtle color accents "
	"and balanced daylight with practical light; avoid an empty shell or a single-color cast. "
	"Leave the main working area open and its surface bare. "
	"The frame is an unoccupied architectural plate, with no inset panels or foreground props."
)


def _architectural_setting(setting):
	"""Keep the place clause while dropping cast/product directions from a mixed setting field."""
	text = str(setting or "").strip()
	match = re.search(
		r"\b(?:mascot|character|actor|person|people|product|package|pack|tissue|box)\b", text, re.I
	)
	if match and match.start() >= 12:
		text = re.sub(
			r"\s*(?:(?:,|and|with|where|while|featuring)\s+)?(?:the|a|an)?\s*$",
			"",
			text[: match.start()],
			flags=re.I,
		)
	return text.rstrip(" ,.;") or "A furnished room"


def render_place(project, setting, view=False, staging=""):
	"""PNG bytes of the empty place (or, `view`, the close view of a split-screen panel's place), drawn by the keyframe
	workflow from its text alone (no reference images)."""
	from joymedia.services.project.context import _project_settings
	from joymedia.services.workflows.comfyui import run_workflow_to_bytes
	from joymedia.services.workflows.resolver import build_execution_workflow
	from joymedia.workflow_adapters import get_workflow_adapter

	workflow_version = _keyframe_workflow(project)
	settings = _project_settings(project)
	from joymedia.services.planning.prompts import MEDIUM_LOCK, _mood

	# The film's own style and mood (the Brand sheet, Tone & Mood): the place is drawn as the frames will be drawn.
	table_guidance = ""
	if "floor work area" in staging:
		table_guidance = (
			"The main action space is a large continuous EMPTY foreground rug or floor, fully visible and "
			"unobstructed. Keep sofas and other furniture at the back or sides. No coffee table or other "
			"raised work surface occupies this foreground floor area. The rug remains completely empty. "
		)
	if "working table" in staging:
		table_guidance = (
			"The main subject is a COMPLETELY EMPTY action tabletop: its entire upper surface "
			"is one continuous exposed material, edge to edge, with only the surface texture visible. "
			"The table is undecorated: zero books, magazines, cups, bowls, trays, vases or plants "
			"on its top or lower shelf. Decorative accents belong on background walls or cabinets. "
			"Use one rigid table whose top and base belong to the same object, with its supports meeting "
			"the floor. Match the table's type, height, footprint, material and perspective to the room "
			"and nearby seating. "
		)
		if _living_room_work_surface(setting, staging):
			table_guidance += (
				"Make it a low coffee table proportionate to the sofa and reachable from the sofa or the "
				"planned floor position, not a full-height dining or work table in front of lounge seating. "
			)
	prompt = (
		f"{table_guidance}{_architectural_setting(setting)}\n\n{VIEW_SETTING if view else LOCATION_PLATE} "
		f"Furnish the location for these upcoming shot compositions and support surfaces: {staging}. "
		"Make the named action furniture prominent and reachable in the foreground; do not make an unmentioned "
		"piece of furniture the room's dominant feature. Keep the foreground floor and seating surfaces exposed. "
		"An unoccupied environmental establishing plate: architecture and furnishings only. The main action "
		"surface is completely bare and the foreground is clear. Wall art uses abstract shapes without faces. "
		+ _mood(project, avoid=False).replace(MEDIUM_LOCK, "")
	).strip()
	from joymedia.services.project.formats import require_dimensions

	width, height = require_dimensions(settings)
	cache_key = hashlib.sha256(
		f"{workflow_version.workflow_hash}:{width}x{height}:{prompt}:location-selection-v4".encode()
	).hexdigest()
	cache = Path(frappe.get_site_path("private", "joymedia-location-cache", cache_key + ".png"))
	if cache.exists():
		return cache.read_bytes()
	# The output node is read from the stored graph: the unused reference branches are already pruned from `workflow`.
	stored = json.loads(workflow_version.workflow_json)
	output_node = get_workflow_adapter(workflow_version).extract_execution_metadata(stored)[
		"primary_output_node_key"
	]
	eligible = []
	for attempt in range(3):
		workflow = build_execution_workflow(
			workflow_version,
			inputs={"generation_prompt": prompt},
			seed=int(hashlib.sha256(f"{prompt}:{attempt}".encode()).hexdigest()[:12], 16),
			width=width,
			height=height,
			fps=float(workflow_version.output_fps or 24),
			frame_count=1,
			output_prefix=f"joymedia/places/{frappe.generate_hash(length=10)}",
		)
		content = run_workflow_to_bytes(workflow, output_node, forget=True)
		frappe.db.commit()  # the render took a while; start a fresh snapshot before writing
		if _location_supports_staging(content, setting, staging):
			eligible.append(content)
			if not _living_room_work_surface(setting, staging) or len(eligible) == 2:
				chosen = _prefer_location_plate(eligible, setting, staging)
				cache.parent.mkdir(parents=True, exist_ok=True)
				cache.write_bytes(chosen)
				return chosen
			continue
		evidence = Path(frappe.get_site_path("private", "joymedia-location-rejections"))
		evidence.mkdir(parents=True, exist_ok=True)
		(evidence / f"{hashlib.sha256(prompt.encode()).hexdigest()[:16]}-{attempt}.png").write_bytes(content)
	if eligible:
		cache.parent.mkdir(parents=True, exist_ok=True)
		cache.write_bytes(eligible[0])
		return eligible[0]
	raise ValueError("The generated place does not support the authored shot staging.")


def _prefer_location_plate(candidates, setting, staging):
	"""Prefer the room whose action furniture fits its seating and actor access.

	A single-image yes/no observer can approve two very different tables. Comparing
	two independently rendered plates supplies the spatial context needed to choose.
	"""
	if len(candidates) < 2:
		return candidates[0]
	from joymedia.services.review.consistency import ask

	try:
		result = ask(
			candidates[:2],
			"These are two alternative empty location plates, in image order. "
			f"Requested setting: {str(setting or '')[:200]}. Planned support: {str(staging or '')[:350]}. "
			"Which plate has a main working table that fits this room best across ALL of these: "
			"(1) height and footprint relative to nearby seating and plausible product scale; "
			"(2) material, finish, and design coherent with the room's furniture; "
			"(3) location, perspective, and reach from the planned actor's seat or floor position, "
			"while leaving clear movement space? Penalize an occupied tabletop. "
			"Judge the table and its physical relationship to the scene, not unrelated decor. "
			"Return JSON with better=1 or 2 "
			"only when the difference is visible, otherwise null, and a short reason.",
			max_edge=1024,
		)
	except Exception:
		frappe.log_error(title="Location plate comparison unavailable")
		return candidates[0]
	return candidates[1] if str(result.get("better")) == "2" else candidates[0]


def _tabletop_crop(content, box, *, pixel_edge=None):
	"""Crop a detected tabletop for a second, detailed observation of loose props."""
	if not isinstance(box, (list, tuple)) or len(box) != 4:
		return None
	try:
		x1, y1, x2, y2 = [float(value) for value in box]
	except (TypeError, ValueError):
		return None
	if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
		return None
	if not (0 <= x1 < x2 and 0 <= y1 < y2):
		return None
	if pixel_edge is None and (x2 > 1000 or y2 > 1000):
		return None
	with Image.open(io.BytesIO(content)) as image:
		width, height = image.size
		if pixel_edge is not None:
			# Vision sees a thumbnail and returns pixel boxes in that image, not
			# the original canvas or a normalized 1000-unit square.
			thumbnail = image.copy()
			thumbnail.thumbnail((pixel_edge, pixel_edge))
			sent_width, sent_height = thumbnail.size
			x1, x2 = [max(0, min(1000, x * 1000 / sent_width)) for x in (x1, x2)]
			y1, y2 = [max(0, min(1000, y * 1000 / sent_height)) for y in (y1, y2)]
			if not (x1 < x2 and y1 < y2):
				return None
		if (x2 - x1) * width / 1000 < 24 or (y2 - y1) * height / 1000 < 12:
			return None
		pad_x, pad_y = (x2 - x1) * 0.07, (y2 - y1) * 0.12
		crop = image.crop(
			(
				max(0, int((x1 - pad_x) * width / 1000)),
				max(0, int((y1 - pad_y) * height / 1000)),
				min(width, int((x2 + pad_x) * width / 1000)),
				min(height, int((y2 + pad_y) * height / 1000)),
			)
		).convert("RGB")
		buffer = io.BytesIO()
		crop.save(buffer, "PNG")
		return buffer.getvalue()


def _location_supports_staging(content, setting, staging):
	"""Use the existing vision observer to reject a room with the wrong furniture or support geometry."""
	from joymedia.services.review.consistency import ask

	try:
		actor = ask(
			content,
			"Is any person, animal, mascot, illustrated character or split-screen panel visible? "
			"Return JSON answer=true if one is visible, false if this is one empty physical location, with reason.",
		)
		if actor.get("answer") is not False:
			return False
		surface_name = (
			"foreground floor or rug action area" if "floor work area" in staging else "main action tabletop"
		)
		foreground = ask(
			content,
			f"Inspect the full {surface_name} at high resolution. List all loose objects resting on it, "
			"including books or magazines. Is the main working surface occupied by ANY loose object or transient action state, including a cup, "
			"liquid, spill, stain, tissue, retail package, printed container, branded box, dispenser, logo or text-bearing product? "
			"Ignore built-in furniture and fixed lighting. The work surface must be bare before the first action. "
			"Return JSON answer=true if any listed object or liquid is visible, false "
			"otherwise, with reason and a list of visible objects.",
			max_edge=1024,
		)
		if foreground.get("answer") is not False:
			return False
		if "floor work area" in staging:
			floor = ask(
				content,
				"Is there a large continuous, empty foreground floor or rug area for a seated actor and product, "
				"with furniture behind or beside it? Answer false if a coffee table or raised surface occupies "
				"the main foreground action space. Return JSON answer true, false or null and reason with visible evidence.",
				schema={
					"type": "object",
					"additionalProperties": False,
					"required": ["answer", "reason"],
					"properties": {
						"answer": {"type": ["boolean", "null"]},
						"reason": {"type": "string", "minLength": 1},
					},
				},
			)
			if floor.get("answer") is not True:
				return False
		if "working table" in staging:
			surface = ask(
				content,
				"Locate the main foreground ACTION TABLETOP, not the sofa, rug, cabinet or table legs. "
				"Return JSON with bbox_2d=[left,top,right,bottom] in PIXEL coordinates of the image you received, "
				"tightly enclosing its visible top surface. Use null if no tabletop is clearly visible.",
				max_edge=1024,
			)
			crop = (
				_tabletop_crop(content, surface["bbox_2d"], pixel_edge=1024)
				if "bbox_2d" in surface
				else _tabletop_crop(content, surface.get("bbox"))
			)
			if crop is None:
				return False
			close_check = ask(
				crop,
				"This is a close crop of the main action tabletop. Is ANY loose object resting on the "
				"surface, including books, magazines, decor, cups, packages, tissue, food, or liquid? "
				"Return JSON answer=true if occupied, false only if the tabletop is visibly bare, "
				"null if uncertain, with objects and visual evidence.",
				max_edge=1024,
			)
			if close_check.get("answer") is not False:
				return False
			table = ask(
				content,
				"Inspect only the main foreground working table. If its entire tabletop and base are visible, "
				"does it have a coherent load-bearing base connected to that one tabletop and meeting the floor, "
				"without a duplicated, fused or floating leg? Return JSON answer=true if visibly correct, "
				"false if visibly incorrect, null if the base is occluded; include reason. "
				"Do not infer hidden legs.",
			)
			if table.get("answer") is False:
				return False
		if LIVING_ROOM.search(str(setting or "")):
			living_room = ask(
				content,
				"Does this setting clearly contain a living-room seating area such as a sofa, couch or lounge armchair, "
				"with visual depth beyond a dining table? Answer false for an empty room or a kitchen/dining room "
				"with only upright dining chairs. Return JSON answer=true or false with visible evidence.",
			)
			if living_room.get("answer") is not True:
				return False
		if _living_room_work_surface(setting, staging):
			fit = ask(
				content,
				"Inspect the MAIN foreground action table relative to the sofa or lounge seating, not "
				"the room's other cabinets. Is it clearly a low coffee table of plausible height and "
				"surface? Does its material, finish and design also fit the room's other furniture? "
				"Answer false for a tall dining/work table, an oversized table that dominates "
				"the seating area, a visibly mismatched material/design, or a table disconnected "
				"from the actor's planned position. Check all three: scale, visual fit and placement. "
				"Return JSON answer=true only when visibly suitable, false when contradicted, null "
				"when the relationship cannot be seen; include visual evidence.",
				max_edge=1024,
			)
			# Some observers answer the three requested checks separately. Require
			# all three explicit positives; never override a negative summary or
			# interpret a missing/uncertain component as a pass.
			fit_answer = fit.get("answer")
			if "answer" not in fit and all(
				fit.get(key) is True for key in ("scale", "visual_fit", "placement")
			):
				fit_answer = True
			if fit_answer is not True:
				return False
		if not staging:
			return True
		result = ask(
			content,
			"This is an EMPTY location plate; actors and advertised products should be absent. "
			f"Requested setting: {setting[:250]}. Upcoming shot staging: {staging[:620]}. "
			"In the center or foreground, is the exact immediate support or action space required by the "
			"stated pose and interaction visibly available at reachable height and depth? For actions involving a "
			"working surface, it must be directly beside the planned actor position. Do not count furniture at a far wall, "
			"a bed, or a distant desk unless the shot names that object as its working support. Also reject a "
			"different kind of room that merely contains incidental furniture. Judge only the empty location, "
			"not the missing actor or product. Answer JSON with answer=true only if visibly suitable, "
			"false if contradicted, or null if uncertain, plus a short reason.",
		)
	except Exception:
		# An unverified location must not be attached to a first frame.
		frappe.log_error(title="Location staging observation unavailable")
		return False
	return result.get("answer") is True


def _location_staging(shot):
	"""Request only support furniture; never copy transient shot props into a shared plate."""
	# Product-view boilerplate lists "table or floor" as generic examples. It
	# must not create an action table absent from the authored opening.
	opening = str(shot.image_prompt or "").split("Product orientation is locked", 1)[0]
	text = " ".join((shot.setting_prompt or "", opening))
	if re.search(r"\b(?:rug|floor|ground)\b", text, re.I) and not re.search(
		r"\b(?:table|desk|counter|worktop)\b", text, re.I
	):
		return "clear foreground floor work area and rug, with furniture behind or beside the action space"
	supports = [
		label
		for label, pattern in (
			("reachable working table", r"\b(?:table|desk|counter|worktop)\b"),
			("physically usable seat", r"\b(?:chair|seat|sofa|couch|bench)\b"),
			("clear floor beside the work area", r"\b(?:floor|standing|walk|step)\b"),
		)
		if re.search(pattern, text, re.I)
	]
	return ", ".join(supports)


def add_place(project, key, setting, content):
	"""Store a place's picture as an Environment reference of the project."""
	# The next free number: places may have been removed, so the count of those left is not it.
	numbers = [
		int(found.group(1))
		for row in project.selected_media or []
		if (row.reference_key or "").startswith("location_")
		and (found := re.match(r"Location (\d+)", row.label or ""))
	]
	number = max(numbers, default=0) + 1
	_store_place(project, key, f"Location {number}: {setting[:80]}", content)


def _store_place(project, key, label, content):
	from joymedia.api.assets import select_project_asset
	from joymedia.services.intake.assets import create_media_asset

	image = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{key}.png",
			"content": content,
			"is_private": 1,
		}
	).insert(ignore_permissions=True)
	asset = create_media_asset(
		label, "Background", file_url=image.file_url, file_name=image.name, source="Generated"
	)
	version = frappe.get_doc("Asset Version", asset["asset_version"])
	analysis = frappe.parse_json(version.analysis_json or "{}") or {}
	analysis["environment_contract"] = {"physical_cast": [], "stage": "empty_location_plate"}
	version.db_set("analysis_json", frappe.as_json(analysis), update_modified=False)
	select_project_asset(project.name, asset["media_asset"], "Environment", label, reference_key=key)


def draw_places_then_frames(project_name, shot_names, user):
	"""Background job: draw the missing places, give them to their scenes, then draw the scenes' first frames."""
	from joymedia.services.keyframes.stage import generate_keyframes

	draw_project_places(project_name, shot_names, user)
	generate_keyframes(project_name, shot_names, draw_places=False)


def draw_project_places(project_name, shot_names, user):
	"""Reuse native shared-setting generation without requiring an image-guided video workflow."""
	frappe.set_user(user)
	project = frappe.get_doc("Media Project", project_name)
	shots = sorted(
		(frappe.get_doc("Shot", name) for name in shot_names),
		key=lambda shot: int(shot.shot_number or 0),
	)
	wanted = [(key, setting, False) for key, setting in missing_places(project, shots).items()]
	wanted += [(key, view, True) for key, view in missing_views(project, shots).items()]
	# The screenplay may call a place merely "cozy room" while its shots need
	# a reachable table, chair or floor. Give the environment renderer the
	# actual opening compositions so it cannot silently substitute a bedroom.
	staging_by_key = {}
	for shot in shots:
		key = place_key(project, shot.setting_prompt)
		opening = _location_staging(shot)
		if opening and key not in staging_by_key:
			staging_by_key[key] = opening
	for key, setting, view in wanted:
		try:
			staging = staging_by_key.get(key, "")
			if view:
				_store_place(
					project,
					key,
					f"Split-screen view: {setting[:80]}",
					render_place(project, setting, view=True, staging=staging),
				)
			else:
				add_place(project, key, setting, render_place(project, setting, staging=staging))
		except Exception:
			frappe.log_error(title=f"Could not draw the place for {project_name}")
			# A scene without its verified environment reference can invent or distort
			# the action furniture. Leave this run failed instead of rendering frames.
			raise
		frappe.db.commit()
		project = frappe.get_doc("Media Project", project_name)
		publish_project_event(project_name, PROJECT_UPDATED, {"doctype": "Media Project"})
	assign_places(project, shots)
	frappe.db.commit()
