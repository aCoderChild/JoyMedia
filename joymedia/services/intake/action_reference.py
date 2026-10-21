"""Observed subject actions from reference footage, using upstream clip analysis.

CameraPath owns probing and frame decoding. OpenStoryline's licensed
understanding prompt owns visual captioning; existing JoyMedia vision transport
owns inference. Captions are observations, never instructions or product claims.
"""

import hashlib
import io
from pathlib import Path

import frappe

from joymedia.services.review.consistency import ask


def analyze_actions(path):
	import json

	from PIL import Image

	from joymedia.vendor.camerapath.video.decoder import FrameDecoder
	from joymedia.vendor.camerapath.video.ffprobe import probe_frames, probe_video

	path = Path(path)
	spec = json.loads(
		(Path(__file__).parents[2] / "workflow_adapters/graphs/action_reference_sampling.json").read_text()
	)
	info = probe_video(path)
	frames, info = probe_frames(info)
	if info.duration_seconds > spec["max_duration_seconds"]:
		raise ValueError("Use a shorter action reference excerpt.")
	if not frames:
		raise ValueError("Action reference has no decodable timestamp evidence.")
	prompt = (Path(__file__).parents[2] / "vendor/open_storyline/understand_clips.md").read_text()
	# Fixed temporal windows are evidence samples, not asserted shot cuts. Short
	# intervals retain contact and consequences lost in whole-shot summaries.
	groups = {}
	for frame in frames:
		bucket = int((frame.time_seconds - frames[0].time_seconds) / spec["window_seconds"])
		groups.setdefault(bucket, []).append(frame)
	sample_groups, wanted = [], set()
	for group in groups.values():
		chosen = [
			group[round(i * (len(group) - 1) / (spec["samples_per_window"] - 1))]
			for i in range(spec["samples_per_window"])
		]
		sample_groups.append(chosen)
		wanted.update(frame.frame_index for frame in chosen)
	decoder = FrameDecoder(info, long_edge=spec["analysis_long_edge"], gray=False)
	pictures = {}
	for index, pixels in decoder.iter_frames(
		start_frame=0, end_frame=len(frames) - 1, start_time=frames[0].time_seconds
	):
		if index in wanted:
			buffer = io.BytesIO()
			Image.fromarray(pixels[:, :, ::-1]).save(buffer, format="JPEG", quality=88)
			pictures[index] = buffer.getvalue()
	clips = []
	for group in sample_groups:
		answer = ask(
			[pictures[frame.frame_index] for frame in group],
			prompt
			+ "\nThese four pictures are chronological video samples at seconds "
			+ ", ".join(f"{frame.time_seconds:.3f}" for frame in group)
			+ ". Prioritize specific visible subject actions, actual contact and changed object state, in order. "
			"Holding or approaching an object alone is not proof of using it. Describe only visible motion, "
			"and say uncertain when the sampled evidence cannot establish the action. Avoid generic 'interacting'. "
			"Do not infer physical correctness, product performance, spoken words or unseen action between samples.",
		)
		caption = answer.get("caption")
		if not isinstance(caption, str) or not caption.strip() or len(caption) > 1800:
			raise ValueError("Reference analysis did not provide a usable action observation.")
		clips.append(
			{
				"start": group[0].time_seconds,
				"end": group[-1].time_seconds,
				"sample_times": [f.time_seconds for f in group],
				"caption": caption.strip(),
				"aesthetic_score": answer.get("aes_score"),
				"evidence": "sampled_temporal_window",
			}
		)
	with path.open("rb") as stream:
		digest = hashlib.file_digest(stream, "sha256").hexdigest()
	return {
		"version": 2,
		"source_sha256": digest,
		"source_name": path.name,
		"clips": clips,
		"sampling": spec,
		"upstream": "FireRed-OpenStoryline@c9e945215586f45c12a61c1951ee9a8e9c43a027",
	}


def action_observations(project):
	from joymedia.services.intake.cinematography import motion_references

	groups = []
	for version in motion_references(project):
		analysis = frappe.parse_json(version.analysis_json or "{}") or {}
		observations = []
		for clip in (analysis.get("action_reference") or {}).get("clips", []):
			observations.append(
				{
					"source": version.name,
					"start": clip["start"],
					"end": clip["end"],
					"observation": clip["caption"],
				}
			)
		groups.append(observations)
	# Interleave sources so a bounded planner context never excludes a later
	# reference entirely. Preserve chronology within each source.
	return [rows[i] for i in range(max(map(len, groups), default=0)) for rows in groups if i < len(rows)]


def ensure_action_analysis(project):
	from joymedia.services.intake.cinematography import motion_references

	for version in motion_references(project):
		stored = frappe.parse_json(version.analysis_json or "{}") or {}
		if (stored.get("action_reference") or {}).get("version") == 2:
			continue
		frappe.get_doc("Media Asset", version.media_asset).check_permission("write")
		stored["action_reference"] = analyze_actions(
			frappe.get_doc("File", {"file_url": version.file}).get_full_path()
		)
		frappe.db.set_value(
			"Asset Version", version.name, "analysis_json", frappe.as_json(stored), update_modified=False
		)
