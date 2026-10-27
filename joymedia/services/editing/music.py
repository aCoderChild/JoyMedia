"""Music briefs, continuous score rendering and timeline music placement."""

import hashlib
import math
import re
import subprocess
import tempfile
from pathlib import Path

import frappe

from joymedia.services.editing.queries import _latest_version_of, _shot_video_clips
from joymedia.services.editing.rendering import _extract_frame, _render_video, _save_output, _video_workflow
from joymedia.services.editing.view import _project_fps

# Bump when score-direction logic changes so a completed project never silently
# reuses an asset rendered with an older prompt contract.
SOUNDTRACK_VERSION = 6


MUSIC_ENDING_SEARCH_SECONDS = 3


SOUNDTRACK_FADE_IN_FRAMES = 12


SOUNDTRACK_FADE_OUT_FRAMES = 72


MUSIC_CLIP_SECONDS = 10


MUSIC_CLIP_SIZE = 384


MUSIC_CROSSFADE_SECONDS = 1.5


MUSIC_GAIN_DB = -12


MUSIC_FADE_OUT_FRAMES = 48


DEFAULT_SOUNDTRACK_MUSIC = ""


def _add_soundtrack(project_name):
	"""Lay one soundtrack under the whole timeline, replacing the per-take audio."""
	project = frappe.get_doc("Media Project", project_name)
	clips = _shot_video_clips(project_name)
	total_frames = max(
		int(clip.timeline_start_frame) + int(clip.source_out_frame) - int(clip.source_in_frame)
		for clip in clips
	)
	music = music_brief(project_name)
	if not music:
		frappe.throw("Describe the background music in the project or storyboard before generating it.")
	# Finishing again (e.g. after regenerating one scene) keeps the same music.
	key = hashlib.sha256(f"{SOUNDTRACK_VERSION}:{music}".encode()).hexdigest()[:8]
	asset_name = f"{project_name} AI Soundtrack {total_frames}f {key}"
	audio_version = _latest_version_of(project_name, asset_name)
	if not audio_version:
		from joymedia.services.planning.llm import to_english

		# The local prompt model may describe music in Vietnamese; render prompts use English.
		audio_version = _render_soundtrack(
			project_name, asset_name, clips[0], to_english(music), total_frames
		)

	from joymedia.services.editing.composer import _get_asset_version_path
	from joymedia.services.editing.timeline import _ensure_source_audio_clips, _timeline_clip_rows

	# The soundtrack is an audio asset; the timeline helper only resolves videos.
	music_start = _music_start_frame(
		_get_asset_version_path(audio_version), total_frames, _project_fps(project_name)
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


def music_brief(project_name):
	"""What the film's music should be: the project's own music text, else the sheet's Tone & Mood and its BGM notes."""
	from joymedia.services.planning.prompts import sheet_brief

	project = frappe.get_doc("Media Project", project_name)
	if (project.soundtrack_prompt or "").strip():
		return project.soundtrack_prompt.strip()
	cues = [
		re.sub(r"^\s*(?:BGM|music|nhạc)\s*:\s*", "", line, flags=re.I).strip()
		for cues in frappe.get_all(
			"Shot",
			filters={"media_project": project_name, "is_removed": 0},
			pluck="audio_cues",
			order_by="shot_number",
		)
		for line in str(cues or "").splitlines()
		if re.match(r"\s*(?:BGM|music|nhạc)\s*:", line, re.I)
	]
	tone = sheet_brief(project)["tone"]
	parts = [
		f"light instrumental background music for a {tone} advertisement"
		if tone
		else DEFAULT_SOUNDTRACK_MUSIC
	]
	if cues:
		parts.append("in the spirit of: " + "; ".join(cues))
	return ", ".join(parts)


def _add_music_bed(project_name):
	"""Lay one music bed under the whole film, beneath the scenes' sound effects (which duck it while they sound)."""
	from joymedia.services.planning.llm import to_english

	clips = _shot_video_clips(project_name)
	total_frames = max(
		int(clip.timeline_start_frame) + int(clip.source_out_frame) - int(clip.source_in_frame)
		for clip in clips
	)
	music = music_brief(project_name)
	if not music:
		frappe.throw("Describe the background music in the project or storyboard before generating it.")
	key = hashlib.sha256(f"{SOUNDTRACK_VERSION}:{music}".encode()).hexdigest()[:8]
	asset_name = f"{project_name} Music bed {total_frames}f {key}"
	audio_version = _latest_version_of(project_name, asset_name) or _render_music_bed(
		project_name, asset_name, clips[0], to_english(music), total_frames
	)
	for clip in frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Audio"},
		fields=["name", "audio_role", "enabled"],
	):
		if clip.audio_role == "BGM":
			frappe.delete_doc("Timeline Clip", clip.name, ignore_permissions=True, force=True)
		elif clip.enabled:
			frappe.db.set_value("Timeline Clip", clip.name, "duck_others", 1, update_modified=False)
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
			"gain_db": MUSIC_GAIN_DB,
			"fade_in_frames": SOUNDTRACK_FADE_IN_FRAMES,
			"fade_out_frames": MUSIC_FADE_OUT_FRAMES,
			"duck_others": 0,
			"transition_to_next": "Cut",
			"transition_frames": 0,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def _render_music_bed(project_name, asset_name, first_clip, music, total_frames):
	from joymedia.services.audio.plan import BGM_WORKFLOW_KEY
	from joymedia.services.editing.export import _asset_version_path
	from joymedia.services.workflows.capabilities import configured_workflow

	music_workflow = configured_workflow("music", legacy_key=BGM_WORKFLOW_KEY)
	if music_workflow:
		return _render_workflow_music_bed(project_name, asset_name, music_workflow, music, total_frames)

	from joymedia.services.audio.direction import score_direction

	prompt = (
		"A still, calm shot; nothing moves. "
		f"Audio: {score_direction(music, total_frames / _project_fps(project_name))}"
	)
	with tempfile.TemporaryDirectory(prefix="joymedia-music-") as temp_dir:
		temp_path = Path(temp_dir)
		first = temp_path / "first.png"
		_extract_frame(_asset_version_path(first_clip.source_asset_version), 0, first)
		from joymedia.services.project.formats import delivery_dimensions, parse_ratio, require_dimensions

		width, height = require_dimensions(frappe.get_doc("Media Project", project_name))
		size = delivery_dimensions(parse_ratio(f"{width}:{height}"), MUSIC_CLIP_SIZE)
		workflow, output_node = _video_workflow(project_name, first, prompt, MUSIC_CLIP_SECONDS, size=size)
		video_path = temp_path / "music.mp4"
		video_path.write_bytes(_render_video(project_name, workflow, output_node))
		bed = temp_path / "music-bed.m4a"
		music_bed(video_path, total_frames / _project_fps(project_name) + 1, bed)
		return _save_output(project_name, asset_name, "Audio", f"{project_name}-music.m4a", bed.read_bytes())


def _render_workflow_music_bed(project_name, asset_name, workflow_name, music, total_frames):
	"""Request a continuous score within the selected workflow's declared capacity."""
	from joymedia.services.workflows.capabilities import capacity
	from joymedia.services.workflows.comfyui import run_workflow_to_bytes
	from joymedia.services.workflows.resolver import build_execution_workflow
	from joymedia.workflow_adapters import get_workflow_adapter

	version = frappe.get_doc("Generation Workflow", workflow_name)
	from joymedia.services.project.formats import require_dimensions

	width, height = require_dimensions(frappe.get_doc("Media Project", project_name))
	provider_fps = float(version.output_fps or 0)
	if provider_fps <= 0:
		raise ValueError("The music workflow must declare output FPS.")
	duration = total_frames / _project_fps(project_name)
	frames = min(math.ceil((duration + 1) * provider_fps), capacity(version))
	continuous = frames / provider_fps >= duration
	from joymedia.services.audio.direction import score_direction

	direction = (
		f"A continuous {frames / provider_fps:g}-second instrumental cue, developing naturally and resolving at the end. "
		if continuous
		else "A loopable instrumental phrase that preserves the described hook, lift and resolve. "
	)
	seed = int(hashlib.sha256(f"{project_name}|{music}".encode()).hexdigest()[:12], 16)
	workflow = build_execution_workflow(
		version,
		inputs={"generation_prompt": direction + score_direction(music, duration)},
		seed=seed,
		width=width,
		height=height,
		fps=provider_fps,
		frame_count=frames,
		output_prefix=f"joymedia/music/{frappe.generate_hash(length=10)}",
	)
	output_node = get_workflow_adapter(version).extract_execution_metadata(workflow)[
		"primary_output_node_key"
	]

	def remember_prompt(prompt_id):
		frappe.db.set_value(
			"Media Project", project_name, "post_production_comfy_prompt_id", prompt_id, update_modified=False
		)
		frappe.db.commit()

	content = run_workflow_to_bytes(
		workflow, output_node, timeout=900, forget=True, on_submitted=remember_prompt
	)
	with tempfile.TemporaryDirectory(prefix="joymedia-music-") as temp_dir:
		phrase, bed = Path(temp_dir) / "phrase.flac", Path(temp_dir) / "bed.m4a"
		phrase.write_bytes(content)
		music_bed(phrase, duration + 1, bed)
		return _save_output(project_name, asset_name, "Audio", f"{project_name}-music.m4a", bed.read_bytes())


def music_bed(clip_path, seconds, output_path, crossfade=MUSIC_CROSSFADE_SECONDS):
	"""The audio of `clip_path` looped to `seconds`, each join an equal-power crossfade (no hard cut or dip where the loop
	restarts)."""
	length = float(
		subprocess.run(
			["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip_path)],
			check=True,
			capture_output=True,
			text=True,
			timeout=60,
		).stdout.strip()
	)
	crossfade = min(crossfade, length / 3)
	copies = max(1, math.ceil((seconds - crossfade) / (length - crossfade)))
	command = ["ffmpeg", "-v", "error", "-y"]
	for _copy in range(copies):
		command += ["-i", str(clip_path)]
	chain, label = [], "[0:a]"
	for index in range(1, copies):
		chain.append(f"{label}[{index}:a]acrossfade=d={crossfade:.3f}:c1=qsin:c2=qsin[x{index}]")
		label = f"[x{index}]"
	chain.append(f"{label}atrim=0:{seconds:.3f},asetpts=PTS-STARTPTS[bed]")
	command += [
		"-filter_complex",
		";".join(chain),
		"-map",
		"[bed]",
		"-c:a",
		"aac",
		"-b:a",
		"192k",
		str(output_path),
	]
	subprocess.run(command, check=True, capture_output=True, timeout=300)
	return output_path


def _render_soundtrack(project_name, asset_name, first_clip, music, total_frames):
	from joymedia.services.editing.export import _asset_version_path

	with tempfile.TemporaryDirectory(prefix="joymedia-soundtrack-") as temp_dir:
		temp_path = Path(temp_dir)
		first = temp_path / "first.png"
		_extract_frame(_asset_version_path(first_clip.source_asset_version), 0, first)
		video_path = temp_path / "soundtrack.mp4"
		workflow, output_node = _soundtrack_workflow(
			project_name, first, music, _soundtrack_seconds(total_frames, _project_fps(project_name))
		)
		video_path.write_bytes(_render_video(project_name, workflow, output_node))
		audio_path = temp_path / "soundtrack.m4a"
		subprocess.run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-i",
				str(video_path),
				"-map",
				"0:a:0",
				"-vn",
				"-c:a",
				"aac",
				"-b:a",
				"192k",
				str(audio_path),
			],
			check=True,
			capture_output=True,
			timeout=300,
		)
		return _save_output(
			project_name, asset_name, "Audio", f"{project_name}-soundtrack.m4a", audio_path.read_bytes()
		)


def _soundtrack_seconds(total_frames, fps):
	# One extra second so the music never ends before the picture, plus room to choose
	# where in the music the film ends (_music_start_frame).
	return total_frames / fps + 1 + MUSIC_ENDING_SEARCH_SECONDS


def _music_start_frame(audio_path, total_frames, fps):
	"""Where the film's music starts, so the film ends on the softest moment of the music.

	Some video workflows do not compose an ending on request, and fading out mid-note sounds cut off.
	The soundtrack is rendered a few seconds longer than the film; starting the music
	up to MUSIC_ENDING_SEARCH_SECONDS later (hidden by its fade-in) moves the film's end
	onto the quietest point there, usually the gap between two phrases.
	"""
	rate, step = 8000, 400  # 50 ms windows
	pcm = subprocess.run(
		["ffmpeg", "-v", "error", "-i", str(audio_path), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
		capture_output=True,
		check=True,
		timeout=120,
	).stdout
	samples = memoryview(pcm).cast("h")
	energy = [
		sum(value * value for value in samples[start : start + step]) / step
		for start in range(0, len(samples) - step, step)
	]
	film_end = round(total_frames / fps * rate / step)
	latest = min(len(energy) - 4, film_end + round(MUSIC_ENDING_SEARCH_SECONDS * rate / step))
	if latest <= film_end:
		return 0
	# Judge each candidate end by the music around it (0.4 s), not one 50 ms window.
	quietest = min(range(film_end, latest + 1), key=lambda index: sum(energy[max(0, index - 4) : index + 4]))
	return round((quietest - film_end) * step / rate * fps)


def _soundtrack_workflow(project_name, first_frame, music, seconds):
	"""Render a soundtrack through the project's declared video workflow."""
	instrumental = "Instrumental music only, no speech, no singing, no sound effects."
	prompt = (
		f"Preserve the supplied scene composition. Audio: {music}. "
		f"The music develops naturally and resolves softly at the end. {instrumental}"
	)
	return _video_workflow(project_name, first_frame, prompt, seconds)
