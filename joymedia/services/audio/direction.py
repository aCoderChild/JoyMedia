"""Turn a score idea into a time-aware commercial direction.

AudioCraft's MusicGen documentation demonstrates that music generation is driven
by a text description, while its JASCO work separates global direction from
local temporal controls.  Tango similarly consumes a concrete text caption.
JoyMedia keeps its configured MMAudio workflow, but supplies that same useful
structure: one global musical identity and explicit changes at editorial beats.
"""

import re

_TEMPO = re.compile(r"\b\d{2,3}\s*(?:bpm|beats?\s*(?:per|/)\s*min(?:ute)?)\b", re.I)
_INSTRUMENT = re.compile(
	r"\b(?:piano|guitar|bass|drum|percussion|marimba|mallet|synth|strings?|clap|ukulele|flute|brass)\b",
	re.I,
)


def score_direction(music: str, duration_seconds: float) -> str:
	"""Return an instrumental score prompt with a clear hook, lift and resolve.

	The caller's musical taste remains the source of truth.  We add arrangement
	information only when it is absent, so a supplied genre, tempo or instrument
	is not silently replaced by a house style.
	"""
	base = re.sub(r"\s+", " ", str(music or "")).strip(" ,.")
	if not base:
		base = "bright tactile commercial score"
	if not _TEMPO.search(base):
		base += ", around 108 BPM"
	if not _INSTRUMENT.search(base):
		base += ", with crisp hand percussion, warm bass and light melodic keys"

	duration = max(6.0, float(duration_seconds or 0))
	hook_end = max(1.5, round(duration * 0.12, 1))
	lift_start = max(hook_end + 1, round(duration * 0.48, 1))
	resolve_start = max(lift_start + 1, round(duration * 0.8, 1))
	return (
		"Original instrumental advertising score. "
		+ base
		+ ". Arrangement map: "
		+ f"0-{hook_end:g}s: begin immediately with one memorable rhythmic motif and a clean accent; "
		+ f"{hook_end:g}-{lift_start:g}s: keep a confident, sparse groove under product action; "
		+ f"{lift_start:g}-{resolve_start:g}s: add a small melodic lift for the proven benefit; "
		+ f"{resolve_start:g}-{duration:g}s: simplify for the CTA, then make a warm final resolve. "
		+ "No vocals, no spoken words, no singing, no sound effects; leave space for narration."
	)


def narration_delivery(position: int, total_spoken_lines: int) -> dict:
	"""A restrained performance contour for providers that expose prosody."""
	if position <= 0:
		return {"rate": "+8%", "pitch": "+2Hz", "role": "hook"}
	if total_spoken_lines > 1 and position >= total_spoken_lines - 1:
		return {"rate": "-4%", "pitch": "+0Hz", "role": "cta"}
	return {"rate": "+0%", "pitch": "+0Hz", "role": "benefit"}


def voiceover_writer_rules() -> str:
	"""Prompt contract for memorable copy without inventing product claims."""
	return (
		"VOICE-OVER ARC: Write lines for the ear, not labels read aloud. The opening spoken line must hook with "
		"a concrete tension, question, contrast or sensory event already visible in the first action; never open with "
		"a generic introduction such as 'Introducing [product]'. A middle line connects one approved claim to the visible "
		"proof. The final line is a short, active CTA. Each line is fresh wording, one thought, and leaves room for the "
		"sound and picture; do not repeat the on-screen text verbatim."
	)
