"""Post-production for generated films: transition bridges and one soundtrack.

Each take is rendered on its own, so cuts are hard and every take brings its own
audio. This step rebuilds the edit timeline from the takes and then

- replaces every cut with a short generated bridge clip that morphs from the
  outgoing take into the incoming one. The bridge overlaps both takes by
  BRIDGE_OVERLAP_FRAMES, so no other clip moves and the film keeps its length;
- generates one MiniMax H3 soundtrack for the whole film and lays it under the
  timeline, replacing the per-take audio.
"""

import copy
import re
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _

from joymedia.services.film_director import PERSON_PATTERN

# 56 frames (2.3 s) sits on MiniMax H3's 17k+5 frame grid.
BRIDGE_OVERLAP_FRAMES = 28
BRIDGE_FRAMES = BRIDGE_OVERLAP_FRAMES * 2
# A take keeps at least this much of itself after both of its bridges.
MIN_TAKE_REMAINDER_FRAMES = 24
SOUNDTRACK_MEGAPIXELS = 0.25
SOUNDTRACK_FADE_IN_FRAMES = 12
SOUNDTRACK_FADE_OUT_FRAMES = 48
COMFYUI_JOB_TIMEOUT_SECONDS = 3600
DEFAULT_SOUNDTRACK_MUSIC = (
	"an elegant cinematic instrumental score, soft piano melody over warm sustained strings, "
	"slowly building with emotion to a gentle swell, then resolving softly at the end"
)
# Node ids of the registered h3_i2v_production graph (see MiniMaxH3ImageToVideoAdapter).
I2V_FIRST_FRAME_NODE = "114"
I2V_RESOLUTION_NODE = "115"
I2V_CONDITIONING_NODE = "105:104"
I2V_SECONDS_NODE = "105:111"
I2V_SAVE_NODE = "92"
I2V_LAST_FRAME_NODE = "joymedia_last_frame"


@frappe.whitelist()
def queue_post_production(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if project.post_production_status in ("Queued", "Running"):
		return {"status": project.post_production_status}
	if not _shot_video_clips(project.name, create=True):
		frappe.throw(_("Generate the scenes before finishing the film."))
	_set_status(project.name, "Queued", step="", error="")
	frappe.enqueue(
		"joymedia.services.post_production.run_post_production",
		queue="long",
		timeout=COMFYUI_JOB_TIMEOUT_SECONDS * 3,
		project_name=project.name,
		enqueue_after_commit=True,
		job_id=f"joymedia:post_production:{project.name}",
		deduplicate=True,
	)
	frappe.db.commit()
	return {"status": "Queued"}


@frappe.whitelist()
def get_post_production_status(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	return {
		"status": project.post_production_status or "Idle",
		"step": project.post_production_step or "",
		"error": project.post_production_error or "",
	}


def run_post_production(project_name: str):
	from joymedia.services.timeline_editor import reset_project_timeline

	_set_status(project_name, "Running", step="Timeline", error="")
	try:
		reset_project_timeline(project_name)
		clips = _shot_video_clips(project_name)
		for index, (outgoing, incoming) in enumerate(zip(clips, clips[1:]), start=1):
			_set_status(project_name, "Running", step=f"Transition {index}/{len(clips) - 1}")
			_insert_bridge(project_name, outgoing, incoming)
			# Later bridges read the trimmed incoming clip.
			clips = _shot_video_clips(project_name)
		_set_status(project_name, "Running", step="Soundtrack")
		_add_soundtrack(project_name)
		_set_status(project_name, "Completed", step="")
	except Exception as exc:
		frappe.db.rollback()
		frappe.log_error(title=f"Post-production failed for {project_name}")
		_set_status(project_name, "Failed", step="", error=str(exc)[:1000])
		raise


def _set_status(project_name, status, step=None, error=None):
	values = {"post_production_status": status}
	if step is not None:
		values["post_production_step"] = step
	if error is not None:
		values["post_production_error"] = error
	frappe.db.set_value("Media Project", project_name, values, update_modified=False)
	frappe.db.commit()


def _shot_video_clips(project_name, create=False):
	from joymedia.services.timeline_editor import get_project_timeline

	if create:
		get_project_timeline(project_name)
	return frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video", "enabled": 1, "shot": ["is", "set"]},
		fields=[
			"name", "shot", "clip_order", "timeline_start_frame", "source_asset_version",
			"source_in_frame", "source_out_frame",
		],
		order_by="timeline_start_frame asc, clip_order asc",
	)


# Transitions


def _insert_bridge(project_name, outgoing, incoming):
	"""Trim both takes by the overlap and put a generated bridge between them."""
	overlap = BRIDGE_OVERLAP_FRAMES
	for clip in (outgoing, incoming):
		if int(clip.source_out_frame) - int(clip.source_in_frame) - overlap < MIN_TAKE_REMAINDER_FRAMES:
			return
	cut_frame = int(incoming.timeline_start_frame)
	bridge_version = _bridge_asset_version(project_name, outgoing, incoming)

	_shift_clip(outgoing.name, source_out_delta=-overlap)
	_shift_clip(incoming.name, source_in_delta=overlap, start_delta=overlap)
	frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": project_name,
			"clip_order": int(outgoing.clip_order or 0),
			"track_type": "Video",
			"track_index": 0,
			"timeline_start_frame": cut_frame - overlap,
			"initial_timeline_start_frame": cut_frame - overlap,
			"enabled": 1,
			"source_asset_version": bridge_version,
			"source_in_frame": 0,
			"source_out_frame": BRIDGE_FRAMES,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": BRIDGE_FRAMES,
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}
	).insert(ignore_permissions=True)
	_renumber_video_clips(project_name)
	frappe.db.commit()


def _shift_clip(clip_name, source_in_delta=0, source_out_delta=0, start_delta=0):
	"""Move a video clip's range and keep its linked source audio aligned."""
	names = [clip_name] + frappe.get_all(
		"Timeline Clip", filters={"linked_video_clip": clip_name}, pluck="name"
	)
	for name in names:
		clip = frappe.get_doc("Timeline Clip", name)
		clip.source_in_frame = int(clip.source_in_frame) + source_in_delta
		clip.source_out_frame = int(clip.source_out_frame) + source_out_delta
		clip.timeline_start_frame = int(clip.timeline_start_frame) + start_delta
		clip.save(ignore_permissions=True)


def _renumber_video_clips(project_name):
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video"},
		fields=["name"],
		order_by="timeline_start_frame asc, clip_order asc",
	)
	for order, clip in enumerate(clips, start=1):
		frappe.db.set_value("Timeline Clip", clip.name, "clip_order", order, update_modified=False)
		for audio in frappe.get_all("Timeline Clip", filters={"linked_video_clip": clip.name}, pluck="name"):
			frappe.db.set_value("Timeline Clip", audio, "clip_order", order, update_modified=False)


def _bridge_asset_version(project_name, outgoing, incoming):
	"""Return a cached bridge for these two takes, or render one."""
	asset_name = (
		f"{project_name} Transition {outgoing.source_asset_version}@{outgoing.source_out_frame}"
		f" > {incoming.source_asset_version}@{incoming.source_in_frame}"
	)
	cached = _latest_version_of(project_name, asset_name)
	if cached:
		return cached

	from joymedia.services.timeline_composer import _asset_version_path

	with tempfile.TemporaryDirectory(prefix="joymedia-bridge-") as temp_dir:
		temp_path = Path(temp_dir)
		first = temp_path / "first.png"
		last = temp_path / "last.png"
		# The bridge starts on the frame after the trimmed outgoing take and ends on
		# the frame before the trimmed incoming take.
		_extract_frame(
			_asset_version_path(outgoing.source_asset_version),
			int(outgoing.source_out_frame) - BRIDGE_OVERLAP_FRAMES,
			first,
		)
		_extract_frame(
			_asset_version_path(incoming.source_asset_version),
			int(incoming.source_in_frame) + BRIDGE_OVERLAP_FRAMES - 1,
			last,
		)
		workflow = _i2v_workflow(
			first,
			_bridge_prompt(outgoing.shot, incoming.shot),
			BRIDGE_FRAMES / 24,
			last_frame=last,
		)
		video_bytes = _render_video(workflow)
	return _save_output(project_name, asset_name, "Video", f"{_slug(asset_name)}.mp4", video_bytes)


def _bridge_prompt(outgoing_shot, incoming_shot):
	prompts = frappe.get_all(
		"Shot", filters={"name": ["in", [outgoing_shot, incoming_shot]]},
		fields=["name", "generation_prompt"],
	)
	by_name = {row.name: row.generation_prompt or "" for row in prompts}
	from_place, to_place = _shot_place(outgoing_shot), _shot_place(incoming_shot)
	movement = (
		"The person keeps moving gracefully while the camera glides with them, and the surroundings"
		if all(PERSON_PATTERN.search(by_name.get(shot, "")) for shot in (outgoing_shot, incoming_shot))
		else "The camera glides smoothly forward and the surroundings"
	)
	identity = (
		" Keep their face, hair and outfit identical."
		if PERSON_PATTERN.search(by_name.get(outgoing_shot, "")) else ""
	)
	return (
		"Seamless cinematic transition from the first frame to the last frame. "
		f"{movement} flow smoothly from {from_place} to {to_place} as a soft warm light sweeps "
		f"across the frame.{identity} One continuous shot with no cuts, smooth stabilized motion, "
		"photorealistic, no text, no deformation. Audio: a soft airy whoosh."
	)


def _shot_place(shot_name):
	"""Name of the place a take is set in: its last reference image."""
	asset_version = frappe.db.get_value(
		"Shot Reference", {"parent": shot_name, "parenttype": "Shot"}, "asset_version", order_by="idx desc"
	)
	media_asset = frappe.db.get_value("Asset Version", asset_version, "media_asset") if asset_version else None
	name = frappe.db.get_value("Media Asset", media_asset, "asset_name") if media_asset else None
	return f"the {name}" if name else "the first place to the next place"


# Soundtrack


def _add_soundtrack(project_name):
	"""Render one soundtrack for the whole timeline and replace the per-take audio with it."""
	from joymedia.services.timeline_composer import _asset_version_path
	from joymedia.services.timeline_editor import _ensure_source_audio_clips, _timeline_clip_rows

	project = frappe.get_doc("Media Project", project_name)
	clips = _shot_video_clips(project_name)
	total_frames = max(
		int(clip.timeline_start_frame) + int(clip.source_out_frame) - int(clip.source_in_frame)
		for clip in clips
	)
	music = (project.soundtrack_prompt or "").strip() or DEFAULT_SOUNDTRACK_MUSIC
	with tempfile.TemporaryDirectory(prefix="joymedia-soundtrack-") as temp_dir:
		temp_path = Path(temp_dir)
		first = temp_path / "first.png"
		_extract_frame(_asset_version_path(clips[0].source_asset_version), 0, first)
		workflow = _i2v_workflow(
			first,
			"A calm cinematic scene with a slow camera drift. "
			f"Audio: {music}. Continuous instrumental music only, no speech, no singing, no sound effects.",
			# One extra second so the music never ends before the picture.
			total_frames / 24 + 1,
			megapixels=SOUNDTRACK_MEGAPIXELS,
		)
		video_path = temp_path / "soundtrack.mp4"
		video_path.write_bytes(_render_video(workflow))
		audio_path = temp_path / "soundtrack.m4a"
		subprocess.run(
			["ffmpeg", "-v", "error", "-y", "-i", str(video_path), "-map", "0:a:0", "-vn",
			 "-c:a", "aac", "-b:a", "192k", str(audio_path)],
			check=True, capture_output=True, timeout=300,
		)
		audio_version = _save_output(
			project_name, f"{project_name} AI Soundtrack", "Audio",
			f"{project_name}-soundtrack.m4a", audio_path.read_bytes(),
		)

	# Bridges bring their own source audio; backfill it so it can be switched off too.
	_ensure_source_audio_clips(project, _timeline_clip_rows(project_name))
	for clip in frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Audio"},
		fields=["name", "audio_role"],
	):
		if clip.audio_role == "Source":
			frappe.db.set_value("Timeline Clip", clip.name, "enabled", 0, update_modified=False)
	frappe.get_doc(
		{
			"doctype": "Timeline Clip",
			"media_project": project_name,
			"clip_order": len(clips) * 2 + 1,
			"track_type": "Audio",
			"track_index": 1,
			"timeline_start_frame": 0,
			"initial_timeline_start_frame": 0,
			"enabled": 1,
			"source_asset_version": audio_version,
			"source_in_frame": 0,
			"source_out_frame": total_frames,
			"initial_source_in_frame": 0,
			"initial_source_out_frame": total_frames,
			"audio_role": "BGM",
			"gain_db": 0,
			"fade_in_frames": SOUNDTRACK_FADE_IN_FRAMES,
			"fade_out_frames": SOUNDTRACK_FADE_OUT_FRAMES,
			"duck_others": 0,
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


# ComfyUI and file helpers


def _i2v_workflow(first_frame, prompt, seconds, last_frame=None, megapixels=None):
	from joymedia.joymedia.doctype.generation_workflow.generation_workflow import get_latest_valid_workflow
	from joymedia.services.comfyui_client import upload_local_file

	source = get_latest_valid_workflow("h3_i2v_production")
	if not source:
		frappe.throw(_("No executable Image-to-Video workflow is configured."))
	workflow = copy.deepcopy(frappe.parse_json(source.workflow_json))
	workflow[I2V_FIRST_FRAME_NODE]["inputs"]["image"] = upload_local_file(first_frame)["server_path"]
	conditioning = workflow[I2V_CONDITIONING_NODE]["inputs"]
	conditioning["prompt"] = prompt
	if last_frame:
		workflow[I2V_LAST_FRAME_NODE] = {
			"class_type": "LoadImage",
			"inputs": {"image": upload_local_file(last_frame)["server_path"]},
		}
		conditioning["last_frame"] = [I2V_LAST_FRAME_NODE, 0]
	if megapixels:
		workflow[I2V_RESOLUTION_NODE]["inputs"]["megapixels"] = megapixels
	workflow[I2V_SECONDS_NODE]["inputs"]["value"] = seconds
	workflow[I2V_SAVE_NODE]["inputs"]["filename_prefix"] = f"joymedia/post/{frappe.generate_hash(length=10)}"
	return workflow


def _render_video(workflow):
	from joymedia.services.comfyui_client import run_workflow_to_bytes

	return run_workflow_to_bytes(workflow, I2V_SAVE_NODE, timeout=COMFYUI_JOB_TIMEOUT_SECONDS, forget=True)


def _extract_frame(video_path, frame_index, output_path):
	subprocess.run(
		["ffmpeg", "-v", "error", "-y", "-i", str(video_path), "-vf", f"select='eq(n,{max(0, frame_index)})'",
		 "-frames:v", "1", "-update", "1", str(output_path)],
		check=True, capture_output=True, timeout=120,
	)
	if not Path(output_path).exists():
		raise ValueError(_("Frame {0} is outside {1}.").format(frame_index, Path(video_path).name))


def _latest_version_of(project_name, asset_name):
	asset = frappe.db.get_value("Media Asset", {"asset_name": asset_name, "media_project": project_name}, "name")
	if not asset:
		return None
	return frappe.db.get_value(
		"Asset Version", {"media_asset": asset}, "name", order_by="version_number desc"
	)


def _save_output(project_name, asset_name, media_type, file_name, content):
	asset = frappe.db.get_value("Media Asset", {"asset_name": asset_name, "media_project": project_name}, "name")
	if not asset:
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"asset_name": asset_name,
				"media_project": project_name,
				"media_type": media_type,
				"asset_category": "Other",
				"asset_scope": "Project Output",
				"status": "Active",
			}
		).insert(ignore_permissions=True).name
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "Media Asset",
			"attached_to_name": asset,
		}
	).insert(ignore_permissions=True)
	version = frappe.get_doc(
		{"doctype": "Asset Version", "media_asset": asset, "file": file_doc.file_url, "source": "Generated"}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return version.name


def _slug(text):
	return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:120]
