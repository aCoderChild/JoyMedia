"""Exact scripted narration, separate from scene effects and music providers."""

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe import _


def spoken_text(value):
	"""Read only the dialogue, never stage directions such as 'VO nữ' or 'Không thoại'."""
	text = str(value or "").strip()
	if re.fullmatch(
		r"(?:không\s+(?:thoại|lời)|no\s+(?:dialogue|speech|voiceover)|none|n/a|x)[.!\s]*", text, re.I
	):
		return ""
	quoted = re.findall(r'[“"]([^”"]+)[”"]', text)
	if quoted:
		return " ".join(quoted).strip()
	return re.sub(
		r"^\s*(?:VO(?:\s+nữ|\s+nam)?|voice[- ]?over|narrat(?:ion|or))\s*:\s*", "", text, flags=re.I
	).strip()


@frappe.whitelist()
def generate_voiceover(project_name, shot_name, voice=None, place=True):
	"""Generate the sheet's exact spoken words and optionally place them on its scene."""
	from joymedia.services.audio.plan import _shot_frame_range, build_audio_plan, place_cue_audio
	from joymedia.services.editing.post_production import _latest_version_of, _save_output

	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	shot = frappe.get_doc("Shot", shot_name)
	if shot.media_project != project.name:
		frappe.throw(_("Shot does not belong to this project."), frappe.PermissionError)
	text = spoken_text(shot.voice_over)
	if not text:
		frappe.throw(_("This scene has no spoken dialogue."))
	from joymedia.services.audio.direction import narration_delivery
	from joymedia.services.audio.synthesis import provider, synthesize

	spoken_shots = [
		row.name
		for row in frappe.get_all(
			"Shot",
			filters={"media_project": project.name, "is_removed": 0},
			fields=["name", "voice_over"],
			order_by="shot_number asc, name asc",
		)
		if spoken_text(row.voice_over)
	]
	delivery = narration_delivery(
		spoken_shots.index(shot.name) if shot.name in spoken_shots else 0, len(spoken_shots)
	)

	configuration = provider(voice, text=text)
	voice = configuration["voice"]
	place = str(place).lower() in {"1", "true", "yes", "on"}
	start, end = _shot_frame_range(project.name, shot.name)
	if place and start is None:
		frappe.throw(_("Render this scene before placing narration."))
	if place:
		existing = next(
			(
				cue
				for cue in build_audio_plan(project.name)
				if cue["shot"] == shot.name and cue["role"] == "Voiceover" and cue["scheduled"]
			),
			None,
		)
		if existing:
			return {"clip": existing["clip"], "already_placed": True}
	seconds = (end - start) / 24 if start is not None else float(shot.duration_seconds or 0)
	key = hashlib.sha256(
		f"v3|{configuration['key']}|{voice}|{text}|{seconds}|{delivery['rate']}|{delivery['pitch']}".encode()
	).hexdigest()[:16]
	asset_name = f"{shot.name} narration {key}"
	version = _latest_version_of(project.name, asset_name)
	if not version:
		with tempfile.TemporaryDirectory(prefix="joymedia-voice-") as temp_dir:
			raw, fitted = Path(temp_dir) / "raw.audio", Path(temp_dir) / "voice.mp3"
			synthesize(text, configuration, raw, seconds, delivery=delivery)
			duration = float(
				subprocess.run(
					[
						"ffprobe",
						"-v",
						"error",
						"-show_entries",
						"format=duration",
						"-of",
						"csv=p=0",
						str(raw),
					],
					check=True,
					capture_output=True,
					text=True,
					timeout=30,
				).stdout.strip()
			)
			rate = max(1, duration / max(0.2, seconds - 0.15))
			if rate > 1.35:
				frappe.throw(
					_(
						"The narration is too long for this scene. Adjust the voice or scene timing before generating it."
					)
				)
			subprocess.run(
				[
					"ffmpeg",
					"-v",
					"error",
					"-y",
					"-i",
					str(raw),
					"-af",
					f"atempo={rate:.6f},afade=t=in:d=0.03",
					"-c:a",
					"libmp3lame",
					"-b:a",
					"192k",
					str(fitted),
				],
				check=True,
				capture_output=True,
				timeout=60,
			)
			frappe.db.commit()  # synthesis took time; release the old read snapshot
			version = _save_output(
				project.name, asset_name, "Audio", f"{shot.name}-voice-{key}.mp3", fitted.read_bytes()
			)
	result = {"asset_version": version, "text": text, "voice": voice, "delivery": delivery}
	if place:
		result.update(place_cue_audio(project.name, shot.name, "Voiceover", version))
	frappe.db.commit()
	return result


def refresh_project_voiceovers(project_name: str):
	"""Replace the placed narration with the current delivery policy.

	This is deliberately separate from ordinary generation: a completed film keeps
	its approved narration until a new version explicitly asks for a refresh.
	"""
	project = frappe.get_doc("Media Project", project_name)
	project._require_write_access()
	for clip in frappe.get_all(
		"Timeline Clip",
		filters={"media_project": project.name, "track_type": "Audio", "audio_role": "Voiceover"},
		pluck="name",
	):
		frappe.delete_doc("Timeline Clip", clip, ignore_permissions=True, force=True)
	frappe.db.commit()
	results = []
	for shot in frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		fields=["name", "voice_over"],
		order_by="shot_number asc, name asc",
	):
		if spoken_text(shot.voice_over):
			results.append(generate_voiceover(project.name, shot.name, place=True))
	return results
