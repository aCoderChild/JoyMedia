"""Executable audio plan: storyboard voice-over and sound cues scheduled on the audio timeline.

A cue is text the advertiser wrote for a shot. It becomes audio only when an audio
asset is placed for it; the asset is positioned at the shot's start on the existing
audio track, so mixing, ducking and export reuse the timeline. Audio can be uploaded
or produced by any service that yields an Audio asset.
"""

import re

import frappe
from frappe import _

CUE_PREFIXES = {"sfx": "SFX", "bgm": "BGM", "music": "BGM", "nhạc": "BGM", "âm thanh": "SFX"}
CUE_LINE = re.compile(r"^\s*([^\W\d_]+(?: [^\W\d_]+)?)\s*[:：]\s*(.+)$", re.UNICODE)


def parse_audio_cues(text):
	"""Split free-form 'SFX: ... / BGM: ...' lines into (role, description) cues."""
	cues = []
	for line in str(text or "").splitlines():
		match = CUE_LINE.match(line)
		role = CUE_PREFIXES.get(match.group(1).casefold()) if match else None
		if role:
			cues.append((role, match.group(2).strip()))
	return cues


def build_audio_plan(project_name):
	"""Every cue of the active shots with its timeline position and whether audio is placed."""
	audio_clips = frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project_name, "track_type": "Audio", "enabled": 1},
		fields=["name", "audio_role", "timeline_start_frame", "source_in_frame", "source_out_frame"],
	)
	plan = []
	for shot in frappe.get_all(
		"Shot",
		filters={"media_project": project_name, "is_removed": 0},
		fields=["name", "shot_name", "voice_over", "audio_cues"],
		order_by="shot_number asc",
	):
		start, end = _shot_frame_range(project_name, shot.name)
		cues = []
		if str(shot.voice_over or "").strip():
			cues.append(("Voiceover", shot.voice_over.strip()))
		cues.extend(parse_audio_cues(shot.audio_cues))
		for role, text in cues:
			clip = next(
				(
					c.name for c in audio_clips
					if c.audio_role == role and start is not None and start <= int(c.timeline_start_frame or 0) < end
				),
				None,
			)
			plan.append({
				"shot": shot.name, "shot_name": shot.shot_name, "role": role, "text": text,
				"start_frame": start, "clip": clip, "scheduled": bool(clip),
			})
	return plan


@frappe.whitelist()
def get_audio_plan(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	return build_audio_plan(project.name)


@frappe.whitelist()
def place_cue_audio(project_name, shot_name, role, asset_version_name):
	"""Place an audio asset for one cue at the start of its shot."""
	from joymedia.services.timeline_editor import add_timeline_audio_clip

	if role not in ("Voiceover", "SFX", "BGM"):
		frappe.throw(_("Audio role must be Voiceover, SFX or BGM."))
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frappe.db.get_value("Shot", shot_name, "media_project") != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	start, _end = _shot_frame_range(project.name, shot_name)
	if start is None:
		frappe.throw(_("This shot has no clip on the timeline yet."))
	existing = {c for c in frappe.get_all("Timeline Clip", filters={"media_project": project.name}, pluck="name")}
	result = add_timeline_audio_clip(project.name, asset_version_name, start, role)
	new_clip = next(name for name in frappe.get_all("Timeline Clip", filters={"media_project": project.name}, pluck="name") if name not in existing)
	if role == "Voiceover":
		# Narration takes priority over music and effects.
		frappe.db.set_value("Timeline Clip", new_clip, "duck_others", 1, update_modified=False)
	return {"clip": new_clip, "start_frame": start, "timeline": result}


GENERATED_AUDIO_ROLES = ("SFX", "BGM")
AUDIO_WORKFLOW_KEY = "mmaudio_video_to_audio"


@frappe.whitelist()
def generate_cue_audio(project_name, shot_name, role="SFX", prompt=None, workflow_key=AUDIO_WORKFLOW_KEY):
	"""Generate audio for a scene from its selected video with a video-to-audio workflow, then place it.

	``prompt`` overrides the storyboard cue text; such models usually respond best to a short
	English description of the sound. Narration is not generated this way (it needs speech synthesis).
	"""
	import hashlib
	import math

	from joymedia.services.comfyui_client import run_workflow_to_bytes, upload_local_file
	from joymedia.services.post_production import _save_output
	from joymedia.services.workflow_resolver import build_execution_workflow
	from joymedia.workflow_adapters import get_workflow_adapter

	if role not in GENERATED_AUDIO_ROLES:
		frappe.throw(_("Audio can be generated for {0}; narration needs a recording or speech synthesis.").format(", ".join(GENERATED_AUDIO_ROLES)))
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	if not shot.selected_output_asset_version:
		frappe.throw(_("Render this scene before generating audio for it."))
	cue_text = str(prompt or "").strip() or next(
		(cue["text"] for cue in build_audio_plan(project.name) if cue["shot"] == shot.name and cue["role"] == role), ""
	)
	if not cue_text:
		frappe.throw(_("This scene has no {0} cue; give a prompt describing the sound.").format(role))
	workflow_name = frappe.db.get_value(
		"Generation Workflow", {"workflow_key": workflow_key}, "name", order_by="version_number desc"
	)
	if not workflow_name:
		frappe.throw(_("No audio generation workflow '{0}' is registered.").format(workflow_key))
	workflow_version = frappe.get_doc("Generation Workflow", workflow_name)
	if workflow_version.output_media_type != "Audio":
		frappe.throw(_("Workflow {0} does not produce audio.").format(workflow_version.name))

	video_url = frappe.db.get_value("Asset Version", shot.selected_output_asset_version, "file")
	video_path = frappe.get_doc("File", {"file_url": video_url}).get_full_path()
	fps = float(workflow_version.output_fps or 24)
	start, end = _shot_frame_range(project.name, shot.name)
	frames = (end - start) if start is not None else math.ceil(float(shot.duration_seconds or 0) * fps)
	frames = max(1, min(int(frames), int(workflow_version.frame_count or frames)))
	seed = int(hashlib.sha256(f"{shot.name}|{role}|{cue_text}".encode()).hexdigest()[:12], 16)
	workflow = build_execution_workflow(
		workflow_version,
		inputs={"generation_prompt": cue_text, "source_video": upload_local_file(video_path)["server_path"]},
		seed=seed, width=int(project.delivery_width or 640), height=int(project.delivery_height or 360),
		fps=fps, frame_count=frames, output_prefix=f"joymedia/audio/{frappe.generate_hash(length=10)}",
	)
	output_node = get_workflow_adapter(workflow_version).extract_execution_metadata(workflow)["primary_output_node_key"]
	content = run_workflow_to_bytes(workflow, output_node, timeout=900, forget=True)
	# The job ran for a while; commit so later writes see current rows.
	frappe.db.commit()
	version = _save_output(project.name, f"{shot.name} {role} audio", "Audio", f"{shot.name}-{role.lower()}.flac", content)
	placed = place_cue_audio(project.name, shot.name, role, version)
	return {"asset_version": version, "workflow": workflow_version.name, "prompt": cue_text, **placed}


@frappe.whitelist()
def use_sound_effects_only(project_name, prompts=None):
	"""Make the soundtrack only sound effects: no voice, no music.

	The video model's own audio mixes voice, effects and music in one stream that cannot be split, so it is
	dropped. Every rendered scene instead gets an effect layer generated from its own video (the storyboard's
	SFX cue, else the sound described in the scene's prompt, else what the video shows), with speech and music
	excluded. `prompts` optionally maps a shot name to the sound description to use.
	"""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	overrides = frappe.parse_json(prompts) if isinstance(prompts, str) and prompts else (prompts or {})
	placed = {cue["shot"] for cue in build_audio_plan(project.name) if cue["role"] == "SFX" and cue["scheduled"]}
	generated, skipped = [], []
	for shot in frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0, "selected_output_asset_version": ["is", "set"]},
		fields=["name", "shot_name", "generation_prompt", "audio_cues"],
		order_by="shot_number asc",
	):
		if shot.name in placed:
			skipped.append(shot.shot_name)
			continue
		prompt = overrides.get(shot.name) or scene_sound_prompt(shot)
		result = generate_cue_audio(project.name, shot.name, "SFX", prompt=prompt)
		generated.append({"shot_name": shot.shot_name, "asset_version": result["asset_version"], "prompt": prompt})
	project.db_set("soundtrack_mode", "Sound effects only")
	from joymedia.services.timeline_editor import _invalidate_project_output

	_invalidate_project_output(project.name)
	frappe.db.commit()
	return {"generated": generated, "already_placed": skipped, "mode": "Sound effects only"}


def scene_sound_prompt(shot):
	"""Describe the effects of a scene: its SFX cue, else its prompt's audio line, else its action.

	Vocal sounds (laughter, voices) are left out, since only sound effects are wanted.
	"""
	from joymedia.services.prompt_compiler import VOCAL_SOUND

	cue = next((text for role, text in parse_audio_cues(shot.audio_cues) if role == "SFX"), None)
	paragraphs = [p.strip() for p in str(shot.generation_prompt or "").split("\n\n") if p.strip()]
	audio = next((p.split(":", 1)[1].strip() for p in paragraphs if p.casefold().startswith("audio:")), None)
	text = cue or audio or (paragraphs[0][:200] if paragraphs else "")
	sentences = [s for s in re.split(r"(?<=[.!])\s+", text) if not VOCAL_SOUND.search(s)]
	return " ".join(sentences) or "natural foley sound effects of the action"


def _shot_frame_range(project_name, shot_name):
	clip = frappe.db.get_value(
		"Timeline Clip",
		{"media_project": project_name, "shot": shot_name, "track_type": "Video", "enabled": 1},
		["timeline_start_frame", "source_in_frame", "source_out_frame"],
		as_dict=True,
	)
	if not clip or clip.timeline_start_frame is None:
		return None, 0
	start = int(clip.timeline_start_frame)
	return start, start + max(0, int(clip.source_out_frame or 0) - int(clip.source_in_frame or 0))
