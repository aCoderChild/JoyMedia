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
