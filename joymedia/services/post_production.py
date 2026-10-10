"""Post-production for generated films: transition bridges and one soundtrack.

Each take is rendered on its own, so cuts are hard and every take brings its own
audio. This step rebuilds the edit timeline from the takes and then

- replaces every cut with a short generated bridge clip that morphs from the
  outgoing take into the incoming one. The bridge overlaps both takes by
  BRIDGE_OVERLAP_FRAMES, so no other clip moves and the film keeps its length;
- generates one soundtrack for the whole film with the project's selected video
  workflow and lays it under the timeline, replacing the per-take audio.
"""

import hashlib
import math
import re
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from joymedia.services.film_director import PERSON_PATTERN
from joymedia.services.render_queue import enqueue_render, is_render_alive

# The default bridge is long enough to conceal a cut while preserving the edit length.
BRIDGE_OVERLAP_FRAMES = 28
BRIDGE_FRAMES = BRIDGE_OVERLAP_FRAMES * 2
# A take keeps at least this much of itself after both of its bridges.
MIN_TAKE_REMAINDER_FRAMES = 24
# Part of the soundtrack cache key: bump it when the soundtrack prompts change.
SOUNDTRACK_VERSION = 3
# Extra soundtrack rendered past the film's end to choose where the music ends.
MUSIC_ENDING_SEARCH_SECONDS = 3
# Conservative default for workflows that produce sound through video segments.
SEGMENT_SECONDS = 5
# Audio/video context shared between soundtrack segments (on the AV prefix grid 39/90/141).
SOUNDTRACK_CONTEXT_FRAMES = 39
SOUNDTRACK_FADE_IN_FRAMES = 12
# A long fade gives every film a deliberate ending when a workflow does not resolve music itself.
SOUNDTRACK_FADE_OUT_FRAMES = 72
COMFYUI_JOB_TIMEOUT_SECONDS = 3600
# Finishing repeats when scenes change while it runs, at most this many times per job.
MAX_FINISHING_ROUNDS = 3
DEFAULT_SOUNDTRACK_MUSIC = (
	"an elegant cinematic instrumental score, soft piano melody over warm sustained strings, "
	"slowly building with emotion to a gentle swell, then resolving softly at the end"
)
@frappe.whitelist()
def queue_post_production(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	# Asked for by hand: rebuild everything, including a timeline edited by hand.
	frappe.db.set_value("Media Project", project.name, "finished_timeline_signature", "", update_modified=False)
	return queue_post_production_internal(project.name)


def queue_post_production_internal(project_name):
	"""Queue Finish film for a project whose caller is already authorized."""
	# A finish already running repeats when it sees a request newer than its start.
	frappe.db.set_value("Media Project", project_name, "post_production_requested_at", now_datetime(), update_modified=False)
	frappe.db.commit()
	status = frappe.db.get_value("Media Project", project_name, "post_production_status")
	if status in ("Queued", "Running") and is_render_alive(_job_id(project_name)):
		return {"status": status}
	if not _shot_video_clips(project_name, create=True):
		frappe.throw(_("Generate the scenes before finishing the film."))
	_set_status(project_name, "Queued", step="", error="")
	enqueue_render(
		"joymedia.services.post_production.run_post_production",
		_job_id(project_name),
		timeout=COMFYUI_JOB_TIMEOUT_SECONDS * 3,
		project_name=project_name,
	)
	frappe.db.commit()
	return {"status": "Queued"}


@frappe.whitelist()
def get_post_production_status(project_name: str):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	if project.post_production_status in ("Queued", "Running") and not is_render_alive(_job_id(project.name)):
		_set_status(project.name, "Failed", step="", error=_("Finishing stopped unexpectedly. Please try again."))
		project.reload()
	return {
		"status": project.post_production_status or "Idle",
		"step": project.post_production_step or "",
		"error": project.post_production_error or "",
	}


def _job_id(project_name):
	return f"joymedia:post_production:{project_name}"


def run_post_production(project_name: str):
	try:
		# Scenes regenerated or takes switched while this ran need another pass.
		for _round in range(MAX_FINISHING_ROUNDS):
			started = now_datetime()
			if _edited_by_hand(project_name):
				# Keep the user's edits: swap new takes in and redo only their transitions.
				_patch_changed_scenes(project_name)
			else:
				_finish_once(project_name)
				frappe.db.set_value(
					"Media Project", project_name, "finished_timeline_signature",
					timeline_signature(project_name), update_modified=False,
				)
			requested = frappe.db.get_value("Media Project", project_name, "post_production_requested_at")
			if not requested or get_datetime(requested) <= started:
				break
		_set_status(project_name, "Completed", step="")
	except Exception as exc:
		frappe.db.rollback()
		frappe.log_error(title=f"Post-production failed for {project_name}")
		from joymedia.services.user_messages import classify_failure, friendly_failure

		# Marketers see a plain message; the technical detail is in the Error Log.
		_set_status(project_name, "Failed", step="", error=friendly_failure(classify_failure(exc, "Generation")))
		raise


def timeline_signature(project_name):
	"""Fingerprint of the editable timeline state."""
	rows = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name},
		fields=[
			"name", "track_type", "track_index", "enabled", "timeline_start_frame", "source_asset_version",
			"source_in_frame", "source_out_frame", "transition_to_next", "transition_frames", "gain_db",
			"fade_in_frames", "fade_out_frames", "audio_role",
		],
		order_by="name asc",
	)
	return hashlib.sha256(repr([tuple(row.values()) for row in rows]).encode()).hexdigest()


def _edited_by_hand(project_name):
	"""Whether the timeline changed since the last full Finish film (trims, moves, mutes...)."""
	finished = frappe.db.get_value("Media Project", project_name, "finished_timeline_signature")
	return bool(finished) and finished != timeline_signature(project_name)


def _patch_changed_scenes(project_name):
	"""Swap each scene's newly selected take into an edited timeline and redo its transitions.

	The user's trims, moves and audio settings stay; the soundtrack stays too.
	"""
	from joymedia.services.timeline_editor import update_timeline_source_for_shot

	_set_status(project_name, "Running", step="Timeline", error="")
	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video", "enabled": 1},
		fields=["name", "shot", "source_asset_version", "source_in_frame", "source_out_frame", "timeline_start_frame", "clip_order"],
		order_by="timeline_start_frame asc, clip_order asc",
	)
	selected = dict(frappe.get_all(
		"Shot", filters={"media_project": project_name}, fields=["name", "selected_output_asset_version"], as_list=True
	))
	changed = {
		clip.shot for clip in clips
		if clip.shot and selected.get(clip.shot) and clip.source_asset_version != selected[clip.shot]
	}
	for shot in changed:
		update_timeline_source_for_shot(project_name, shot)

	generation_mode = frappe.db.get_value("Media Project", project_name, "generation_mode") or "Multi-shot"
	if generation_mode in ("Continuous", "Consistency"):
		frappe.db.commit()
		return

	clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Video", "enabled": 1},
		fields=["name", "shot", "source_asset_version", "source_in_frame", "source_out_frame", "timeline_start_frame", "clip_order"],
		order_by="timeline_start_frame asc, clip_order asc",
	)
	bridges = [
		(previous, bridge, following)
		for previous, bridge, following in zip(clips, clips[1:], clips[2:])
		if not bridge.shot and (previous.shot in changed or following.shot in changed)
	]
	for index, (previous, bridge, following) in enumerate(bridges, start=1):
		_set_status(project_name, "Running", step=f"Transition {index}/{len(bridges)}")
		outgoing = frappe._dict(previous, source_out_frame=int(previous.source_out_frame) + BRIDGE_OVERLAP_FRAMES)
		incoming = frappe._dict(following, source_in_frame=int(following.source_in_frame) - BRIDGE_OVERLAP_FRAMES)
		try:
			version = _bridge_asset_version(project_name, outgoing, incoming)
		except (subprocess.CalledProcessError, ValueError):
			frappe.log_error(title=f"Transition not redone for {project_name}")
			continue
		frappe.db.set_value("Timeline Clip", bridge.name, "source_asset_version", version, update_modified=False)
	frappe.db.commit()


def _finish_once(project_name):
	from joymedia.services.timeline_editor import reset_project_timeline

	_set_status(project_name, "Running", step="Timeline", error="")
	reset_project_timeline(project_name)
	clips = _shot_video_clips(project_name)
	generation_mode = frappe.db.get_value("Media Project", project_name, "generation_mode") or "Multi-shot"
	if generation_mode not in ("Continuous", "Consistency"):
		for index, (outgoing, incoming) in enumerate(zip(clips, clips[1:]), start=1):
			_set_status(project_name, "Running", step=f"Transition {index}/{len(clips) - 1}")
			_insert_bridge(project_name, outgoing, incoming)
			clips = _shot_video_clips(project_name)
	_set_status(project_name, "Running", step="Soundtrack")
	_add_soundtrack(project_name)


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
		workflow, output_node = _video_workflow(
			project_name,
			first,
			_bridge_prompt(outgoing.shot, incoming.shot),
			BRIDGE_FRAMES / 24,
			last_frame=last,
		)
		video_bytes = _render_video(workflow, output_node)
	return _save_output(project_name, asset_name, "Video", f"{_slug(asset_name)}.mp4", video_bytes)


def _bridge_prompt(outgoing_shot, incoming_shot):
	prompts = frappe.get_all(
		"Shot", filters={"name": ["in", [outgoing_shot, incoming_shot]]},
		fields=["name", "generation_prompt"],
	)
	by_name = {row.name: row.generation_prompt or "" for row in prompts}
	from_place, to_place = _shot_place(outgoing_shot), _shot_place(incoming_shot)
	journey = (
		f"flow smoothly from {from_place} to {to_place}"
		if from_place and to_place and from_place != to_place
		else "flow smoothly into the next moment"
	)
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
		f"{movement} {journey} as a soft warm light sweeps "
		f"across the frame.{identity} One continuous shot with no cuts, smooth stabilized motion, "
		"photorealistic, no text, no deformation. Audio: a soft airy whoosh."
	)


def _shot_place(shot_name):
	"""Name of the place a take is set in (its last reference image), or None.

	A take whose last reference is a product, not a place, has no place name: a product
	called "1" must not become "the 1" in a transition prompt.
	"""
	from joymedia.services.film_director import PLACE, _asset_version_context, classify_reference

	asset_version = frappe.db.get_value(
		"Shot Reference", {"parent": shot_name, "parenttype": "Shot"}, "asset_version", order_by="idx desc"
	)
	if not asset_version:
		return None
	project = frappe.db.get_value("Shot", shot_name, "media_project")
	reference = frappe.db.get_value(
		"Project Reference", {"parent": project, "asset_version": asset_version}, ["reference_role", "label"], as_dict=True
	) or {}
	if classify_reference(_asset_version_context(asset_version, reference)) != PLACE:
		return None
	media_asset = frappe.db.get_value("Asset Version", asset_version, "media_asset")
	name = frappe.db.get_value("Media Asset", media_asset, "asset_name") if media_asset else None
	return f"the {name}" if name else None


# Soundtrack


def _add_soundtrack(project_name):
	"""Lay one soundtrack under the whole timeline, replacing the per-take audio."""
	project = frappe.get_doc("Media Project", project_name)
	clips = _shot_video_clips(project_name)
	total_frames = max(
		int(clip.timeline_start_frame) + int(clip.source_out_frame) - int(clip.source_in_frame)
		for clip in clips
	)
	music = (project.soundtrack_prompt or "").strip() or DEFAULT_SOUNDTRACK_MUSIC
	# Finishing again (e.g. after regenerating one scene) keeps the same music.
	key = hashlib.sha256(f"{SOUNDTRACK_VERSION}:{music}".encode()).hexdigest()[:8]
	asset_name = f"{project_name} AI Soundtrack {total_frames}f {key}"
	audio_version = _latest_version_of(project_name, asset_name)
	if not audio_version:
		from joymedia.services.qwen_client import to_english

		# The local prompt model may describe music in Vietnamese; render prompts use English.
		audio_version = _render_soundtrack(project_name, asset_name, clips[0], to_english(music), total_frames)

	from joymedia.services.timeline_editor import _ensure_source_audio_clips, _timeline_clip_rows
	from joymedia.services.video_composer import _get_asset_version_path

	# The soundtrack is an audio asset; the timeline helper only resolves videos.
	music_start = _music_start_frame(_get_asset_version_path(audio_version), total_frames)
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
			"source_in_frame": music_start,
			"source_out_frame": music_start + total_frames,
			"initial_source_in_frame": music_start,
			"initial_source_out_frame": music_start + total_frames,
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


def _render_soundtrack(project_name, asset_name, first_clip, music, total_frames):
	from joymedia.services.timeline_composer import _asset_version_path

	with tempfile.TemporaryDirectory(prefix="joymedia-soundtrack-") as temp_dir:
		temp_path = Path(temp_dir)
		first = temp_path / "first.png"
		_extract_frame(_asset_version_path(first_clip.source_asset_version), 0, first)
		video_path = temp_path / "soundtrack.mp4"
		workflow, output_node = _soundtrack_workflow(
			project_name, first, music, _soundtrack_seconds(total_frames)
		)
		video_path.write_bytes(_render_video(workflow, output_node))
		audio_path = temp_path / "soundtrack.m4a"
		subprocess.run(
			["ffmpeg", "-v", "error", "-y", "-i", str(video_path), "-map", "0:a:0",
			 "-vn", "-c:a", "aac", "-b:a", "192k", str(audio_path)],
			check=True, capture_output=True, timeout=300,
		)
		return _save_output(
			project_name, asset_name, "Audio", f"{project_name}-soundtrack.m4a", audio_path.read_bytes()
		)


def _soundtrack_seconds(total_frames):
	# One extra second so the music never ends before the picture, plus room to choose
	# where in the music the film ends (_music_start_frame).
	return total_frames / 24 + 1 + MUSIC_ENDING_SEARCH_SECONDS


def _music_start_frame(audio_path, total_frames):
	"""Where the film's music starts, so the film ends on the softest moment of the music.

	Some video workflows do not compose an ending on request, and fading out mid-note sounds cut off.
	The soundtrack is rendered a few seconds longer than the film; starting the music
	up to MUSIC_ENDING_SEARCH_SECONDS later (hidden by its fade-in) moves the film's end
	onto the quietest point there, usually the gap between two phrases.
	"""
	rate, step = 8000, 400  # 50 ms windows
	pcm = subprocess.run(
		["ffmpeg", "-v", "error", "-i", str(audio_path), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
		capture_output=True, check=True, timeout=120,
	).stdout
	samples = memoryview(pcm).cast("h")
	energy = [
		sum(value * value for value in samples[start:start + step]) / step
		for start in range(0, len(samples) - step, step)
	]
	film_end = round(total_frames / 24 * rate / step)
	latest = min(len(energy) - 4, film_end + round(MUSIC_ENDING_SEARCH_SECONDS * rate / step))
	if latest <= film_end:
		return 0
	# Judge each candidate end by the music around it (0.4 s), not one 50 ms window.
	quietest = min(range(film_end, latest + 1), key=lambda index: sum(energy[max(0, index - 4):index + 4]))
	return round((quietest - film_end) * step / rate * 24)


def segment_durations(seconds, max_segment_seconds=SEGMENT_SECONDS, fps=24):
	"""Equal segments of about max_segment_seconds that together last at least seconds.

	The configured segment grid has a small frame offset. Size each segment on
	that grid so a long soundtrack does not return shorter than requested.
	"""
	frames = math.ceil(seconds * fps)
	fewest = max(1, math.ceil(frames / (max_segment_seconds * fps)))

	def plan(count):
		per_segment = math.ceil(frames / count)
		return count, per_segment + (5 - per_segment % 17) % 17

	count, per_segment = min((plan(count) for count in range(fewest, fewest + 3)), key=lambda p: p[0] * p[1])
	# Half a frame of headroom so float rounding never snaps a segment down a step.
	return [(per_segment + 0.5) / fps] * count


def segmented_prompt(prompts, durations):
	"""One [Shot N] prompt block per segment with its cut time."""
	blocks, start = [], 0.0
	for index, (prompt, duration) in enumerate(zip(prompts, durations), start=1):
		cut = "" if index == 1 else f"At {int(start // 60):02d}:{start % 60:06.3f}, "
		blocks.append(f"[Shot {index}] {cut}{prompt}")
		start += duration
	return "\n---\n".join(blocks)


def _soundtrack_workflow(project_name, first_frame, music, seconds):
	"""Render a soundtrack through the project's declared video workflow."""
	instrumental = "Instrumental music only, no speech, no singing, no sound effects."
	prompt = (
		f"A calm cinematic scene with a slow camera drift. Audio: {music}. "
		f"The music develops naturally and resolves softly at the end. {instrumental}"
	)
	return _video_workflow(project_name, first_frame, prompt, seconds)


# ComfyUI and file helpers


def _video_workflow(project_name, first_frame, prompt, seconds, last_frame=None):
	"""Build a post-production prompt solely from the selected workflow contract.

	An optional ``last_frame`` is sent only to workflows that explicitly declare
	it.  This makes transition quality a workflow capability, not a backend
	branch tied to a provider, node id, or model name.
	"""
	from joymedia.services.comfyui_client import upload_local_file
	from joymedia.services.workflow_resolver import build_execution_workflow, get_workflow_input_contract
	from joymedia.workflow_adapters import get_workflow_adapter

	project = frappe.get_doc("Media Project", project_name)
	if not project.workflow:
		frappe.throw(_("Select a video generation workflow before finishing the film."))
	workflow_version = frappe.get_doc("Generation Workflow", project.workflow)
	contract = {item["role"]: item for item in get_workflow_input_contract(workflow_version)}
	if workflow_version.output_media_type != "Video" or "first_frame" not in contract:
		frappe.throw(_("The selected workflow cannot render video from a first frame."))
	inputs = {
		"generation_prompt": prompt,
		"first_frame": upload_local_file(first_frame)["server_path"],
	}
	if last_frame and "last_frame" in contract:
		inputs["last_frame"] = upload_local_file(last_frame)["server_path"]
	fps = float(workflow_version.output_fps or 24)
	frame_count = max(1, math.ceil(float(seconds) * fps))
	seed_material = f"{project_name}|{prompt}|{frame_count}|{first_frame}|{last_frame or ''}"
	workflow = build_execution_workflow(
		workflow_version,
		inputs=inputs,
		seed=int(hashlib.sha256(seed_material.encode()).hexdigest()[:12], 16),
		width=int(project.delivery_width or 1920),
		height=int(project.delivery_height or 1080),
		fps=fps,
		frame_count=frame_count,
		output_prefix=f"joymedia/post/{frappe.generate_hash(length=10)}",
	)
	metadata = get_workflow_adapter(workflow_version).extract_execution_metadata(workflow)
	return workflow, metadata["primary_output_node_key"]


def _render_video(workflow, output_node):
	from joymedia.services.comfyui_client import run_workflow_to_bytes

	content = run_workflow_to_bytes(workflow, output_node, timeout=COMFYUI_JOB_TIMEOUT_SECONDS, forget=True)
	# The render took minutes; MariaDB's snapshot isolation rejects writes to rows
	# (such as naming series) that other workers changed since this transaction began.
	frappe.db.commit()
	return content


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
