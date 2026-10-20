"""Executable audio plan: storyboard voice-over and sound cues scheduled on the audio timeline.

A cue is text the advertiser wrote for a shot. It becomes audio only when an audio
asset is placed for it; the asset is positioned at the shot's start on the existing
audio track, so mixing, ducking and export reuse the timeline. Audio can be uploaded
or produced by any service that yields an Audio asset.
"""

import re

import frappe
from frappe import _

from joymedia.services.project.tuning import tune

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
		from joymedia.services.audio.speech import spoken_text

		if spoken_text(shot.voice_over):
			cues.append(("Voiceover", shot.voice_over.strip()))
		cues.extend(parse_audio_cues(shot.audio_cues))
		for role, text in cues:
			clip = next(
				(
					c.name
					for c in audio_clips
					if c.audio_role == role
					and start is not None
					and start <= int(c.timeline_start_frame or 0) < end
				),
				None,
			)
			plan.append(
				{
					"shot": shot.name,
					"shot_name": shot.shot_name,
					"role": role,
					"text": text,
					"start_frame": start,
					"clip": clip,
					"scheduled": bool(clip),
				}
			)
	return plan


@frappe.whitelist()
def get_audio_plan(project_name):
	project = frappe.get_doc("Media Project", project_name)
	project._require_read_access()
	return build_audio_plan(project.name)


@frappe.whitelist()
def place_cue_audio(project_name, shot_name, role, asset_version_name):
	"""Place an audio asset for one cue at the start of its shot."""
	from joymedia.services.editing.timeline import add_timeline_audio_clip

	if role not in ("Voiceover", "SFX", "BGM"):
		frappe.throw(_("Audio role must be Voiceover, SFX or BGM."))
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	if frappe.db.get_value("Shot", shot_name, "media_project") != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	start, _end = _shot_frame_range(project.name, shot_name)
	if start is None:
		frappe.throw(_("This shot has no clip on the timeline yet."))
	existing = {
		c for c in frappe.get_all("Timeline Clip", filters={"media_project": project.name}, pluck="name")
	}
	result = add_timeline_audio_clip(project.name, asset_version_name, start, role)
	new_clip = next(
		name
		for name in frappe.get_all("Timeline Clip", filters={"media_project": project.name}, pluck="name")
		if name not in existing
	)
	# Retain ownership so rerendered effects replace this scene's earlier layer.
	frappe.db.set_value("Timeline Clip", new_clip, "shot", shot_name, update_modified=False)
	if role == "Voiceover":
		# Narration takes priority over music and effects.
		frappe.db.set_value("Timeline Clip", new_clip, "duck_others", 1, update_modified=False)
	return {"clip": new_clip, "start_frame": start, "timeline": result}


GENERATED_AUDIO_ROLES = ("SFX", "BGM")
AUDIO_WORKFLOW_KEY = "mmaudio_video_to_audio"
BGM_WORKFLOW_KEY = "mmaudio_bgm"


@frappe.whitelist()
def generate_cue_audio(
	project_name,
	shot_name,
	role="SFX",
	prompt=None,
	workflow_key=AUDIO_WORKFLOW_KEY,
	seed_offset=0,
	place=True,
):
	"""Generate audio for a scene from its selected video with a video-to-audio workflow, then place it.

	``prompt`` overrides the storyboard cue text; such models usually respond best to a short
	English description of the sound. Narration is not generated this way (it needs speech synthesis).
	"""
	import hashlib
	import math

	from joymedia.services.editing.post_production import _save_output
	from joymedia.services.workflows.comfyui import run_workflow_to_bytes, upload_local_file
	from joymedia.services.workflows.resolver import build_execution_workflow
	from joymedia.workflow_adapters import get_workflow_adapter

	if role not in GENERATED_AUDIO_ROLES:
		frappe.throw(
			_("Audio can be generated for {0}; narration needs a recording or speech synthesis.").format(
				", ".join(GENERATED_AUDIO_ROLES)
			)
		)
	if role == "BGM" and workflow_key == AUDIO_WORKFLOW_KEY:
		workflow_key = BGM_WORKFLOW_KEY
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."))
	if not shot.selected_output_asset_version:
		frappe.throw(_("Render this scene before generating audio for it."))
	cue_text = str(prompt or "").strip() or next(
		(
			cue["text"]
			for cue in build_audio_plan(project.name)
			if cue["shot"] == shot.name and cue["role"] == role
		),
		"",
	)
	if not cue_text:
		frappe.throw(_("This scene has no {0} cue; give a prompt describing the sound.").format(role))
	from joymedia.services.workflows.capabilities import configured_workflow

	workflow_name = configured_workflow("music" if role == "BGM" else "effects", legacy_key=workflow_key)
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
	seed = int(hashlib.sha256(f"{shot.name}|{role}|{cue_text}".encode()).hexdigest()[:12], 16) + int(
		seed_offset
	)
	inputs = {"generation_prompt": cue_text}
	if any(row.required_input_role == "source_video" for row in workflow_version.bindings):
		inputs["source_video"] = upload_local_file(video_path)["server_path"]
	workflow = build_execution_workflow(
		workflow_version,
		inputs=inputs,
		seed=seed,
		width=int(project.delivery_width or 640),
		height=int(project.delivery_height or 360),
		fps=fps,
		frame_count=frames,
		output_prefix=f"joymedia/audio/{frappe.generate_hash(length=10)}",
	)
	output_node = get_workflow_adapter(workflow_version).extract_execution_metadata(workflow)[
		"primary_output_node_key"
	]
	content = run_workflow_to_bytes(workflow, output_node, timeout=900, forget=True)
	# The job ran for a while; commit so later writes see current rows.
	frappe.db.commit()
	version = _save_output(
		project.name, f"{shot.name} {role} audio", "Audio", f"{shot.name}-{role.lower()}.flac", content
	)
	placed = place_cue_audio(project.name, shot.name, role, version) if place else {}
	return {"asset_version": version, "workflow": workflow_version.name, "prompt": cue_text, **placed}


@frappe.whitelist()
def use_separate_effects_layer(project_name, prompts=None):
	"""Guarantee a soundtrack of sound effects only, by replacing the video model's own audio.

	That audio mixes voice, effects and music in one stream that cannot be split, so it is dropped. Every rendered scene instead gets an effect layer generated from its own video (the storyboard's
	SFX cue, else the sound described in the scene's prompt, else what the video shows), with speech and music
	excluded. `prompts` optionally maps a shot name to the sound description to use.
	"""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	overrides = frappe.parse_json(prompts) if isinstance(prompts, str) and prompts else (prompts or {})
	placed = {
		cue["shot"] for cue in build_audio_plan(project.name) if cue["role"] == "SFX" and cue["scheduled"]
	}
	generated, skipped = [], []
	for shot in frappe.get_all(
		"Shot",
		filters={
			"media_project": project.name,
			"is_removed": 0,
			"selected_output_asset_version": ["is", "set"],
		},
		fields=["name", "shot_name", "generation_prompt", "audio_cues"],
		order_by="shot_number asc",
	):
		if shot.name in placed:
			skipped.append(shot.shot_name)
			continue
		prompt = overrides.get(shot.name) or scene_sound_prompt(shot)
		result = generate_cue_audio(project.name, shot.name, "SFX", prompt=prompt)
		generated.append(
			{"shot_name": shot.shot_name, "asset_version": result["asset_version"], "prompt": prompt}
		)
	project.db_set("soundtrack_mode", "Separate effects layer")
	from joymedia.services.editing.timeline import _invalidate_project_output

	_invalidate_project_output(project.name)
	frappe.db.commit()
	return {"generated": generated, "already_placed": skipped, "mode": "Separate effects layer"}


@frappe.whitelist()
def check_scene_audio(project_name, apply=True):
	"""Screen each scene's own audio and replace the ones that sound like music or a voice.

	The video model's audio cannot be told reliably to leave music or voice out. A scene whose audio is not
	noise-like (see audio_check) gets a generated sound-effect layer instead, and its own audio is muted on the
	timeline; scenes that pass keep their own audio. Returns one row per scene with its score and what was done.
	With apply=0 nothing is changed.
	"""
	from joymedia.services.audio.check import effects_score
	from joymedia.services.editing.composer import _get_asset_version_path
	from joymedia.services.editing.timeline import _invalidate_project_output

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	apply = str(apply).lower() in {"1", "true", "yes", "on"}
	layers = {
		cue["shot"]: cue["clip"]
		for cue in build_audio_plan(project.name)
		if cue["role"] == "SFX" and cue["scheduled"]
	}
	report = []
	for clip in frappe.get_all(
		"Timeline Clip",
		filters={
			"media_project": project.name,
			"track_type": "Audio",
			"audio_role": "Source",
			"shot": ["is", "set"],
		},
		fields=["name", "shot", "source_asset_version", "enabled"],
	):
		layer_clip = layers.get(clip.shot)
		if layer_clip and not _layer_is_stale(layer_clip, clip.source_asset_version):
			# A layer made for this scene's current video stays; its own audio stays muted.
			report.append(
				{
					"shot": clip.shot,
					"shot_name": frappe.db.get_value("Shot", clip.shot, "shot_name"),
					"score": None,
					"action": "layer kept",
				}
			)
			continue
		if layer_clip and apply:
			frappe.delete_doc("Timeline Clip", layer_clip, force=True, ignore_permissions=True)
			layers.pop(clip.shot)
		if not clip.enabled and apply:
			# A new take of the scene: judge its own audio again.
			frappe.db.set_value("Timeline Clip", clip.name, "enabled", 1, update_modified=False)
		score = effects_score(_get_asset_version_path(clip.source_asset_version))
		row = {
			"shot": clip.shot,
			"shot_name": frappe.db.get_value("Shot", clip.shot, "shot_name"),
			"score": score,
			"action": "kept",
		}
		if score is not None and tune("effects_flatness_min") <= score < tune("effects_borderline_max"):
			row["listen"] = True  # accepted, but close to the line
		if score is not None and score < tune("effects_flatness_min"):
			row["action"] = "replaced"
			if apply:
				row["layer_score"] = _place_best_effects_layer(project.name, clip.shot)
				if row["layer_score"] is None or row["layer_score"] < tune("effects_layer_accept_min"):
					row["action"] = "silenced"
				elif row["layer_score"] < tune("effects_flatness_min"):
					row["listen"] = True
				frappe.db.set_value("Timeline Clip", clip.name, "enabled", 0, update_modified=False)
		report.append(row)
	if apply:
		_invalidate_project_output(project.name)
		frappe.db.commit()
	return report


def _layer_is_stale(layer_clip, video_version):
	"""A generated layer older than the scene's current video was made for an earlier take."""
	layer_version = frappe.db.get_value("Timeline Clip", layer_clip, "source_asset_version")
	return frappe.db.get_value("Asset Version", layer_version, "creation") < frappe.db.get_value(
		"Asset Version", video_version, "creation"
	)


def _place_best_effects_layer(project_name, shot_name):
	"""Generate an effect layer that passes the effects screen and place it; None when none does.

	Each retry changes the seed and the wording (a laughing face makes the model hum or voice, whatever the
	seed). A layer that never passes is not placed: a silent scene is safer than one with music or a voice.
	Returns the best score reached.
	"""
	from joymedia.services.audio.check import effects_score
	from joymedia.services.editing.composer import _get_asset_version_path

	base = scene_sound_prompt(frappe.get_doc("Shot", shot_name))
	prompts = [
		base,
		f"dry close-up foley recording of {base.rstrip('.')}, no ambience, no tones",
		"rustling, crinkling and soft impacts only, dry, no tones, no humming",
	]
	best = None
	for attempt in range(int(tune("effect_layer_attempts"))):
		version = generate_cue_audio(
			project_name,
			shot_name,
			"SFX",
			prompt=prompts[attempt % len(prompts)],
			seed_offset=attempt,
			place=False,
		)["asset_version"]
		score = effects_score(_get_asset_version_path(version))
		if best is None or (score or 0) > (best[1] or 0):
			best = (version, score)
		if score is not None and score >= tune("effects_flatness_min"):
			break
	# A layer that clearly passes is used. One in the borderline band is still better than a silent scene, and is
	# flagged to be listened to; below that the scene stays silent rather than carry music or a voice.
	if best[1] is not None and best[1] >= tune("effects_layer_accept_min"):
		# One layer per scene: a re-run replaces the scene's earlier layer instead of stacking another on it.
		for stale in frappe.get_all(
			"Timeline Clip",
			filters={"media_project": project_name, "shot": shot_name, "audio_role": "SFX"},
			pluck="name",
		):
			frappe.delete_doc("Timeline Clip", stale, force=True, ignore_permissions=True)
		place_cue_audio(project_name, shot_name, "SFX", best[0])
	return best[1]


DEFAULT_FOLEY = "Silence, no sound effects."


def scene_sound_prompt(shot):
	"""English description of a scene's sound effects for the audio model.

	The sound-effect model is trained on English, so the planner's English `Audio:` line in the scene's prompt is
	preferred over the storyboard's own cue (which may be in another language). A scene with no sound cue gets a
	silence, never invented prop sounds or its visual description. Vocal sounds (laughter, voices, exclamations) are left
	out, since only sound effects are wanted.
	"""
	from joymedia.services.planning.prompts import VOCAL_SOUND

	paragraphs = [p.strip() for p in str(shot.generation_prompt or "").split("\n\n") if p.strip()]
	line = next((p.split(":", 1)[1].strip() for p in paragraphs if p.casefold().startswith("audio:")), "")
	text = re.sub(r"^sound effects\s*:\s*", "", line, flags=re.I)
	if not text or not _is_english(text):
		# No usable English audio line: the sheet's cue, only if it is English too.
		cue = next((t for role, t in parse_audio_cues(shot.audio_cues) if role == "SFX"), "")
		text = cue if _is_english(cue) else ""
	# The prompt compiler's own additions (timed events, the "no speech" sentence) are not part of the description.
	text = re.split(r"\bSound effects only:", text)[0]
	text = re.sub(r"\bat \d+(?:\.\d+)?s\b", "", text)
	sentences = [x for x in re.split(r"(?<=[.!])\s+", text) if x.strip() and not VOCAL_SOUND.search(x)]
	described = " ".join(sentences).replace("silence between the sounds", "").strip(" .;,")
	return described or DEFAULT_FOLEY


def _is_english(text):
	from joymedia.services.planning.production import looks_english

	return bool(text) and looks_english(text)


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
