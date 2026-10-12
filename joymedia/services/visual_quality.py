"""Automated, fail-closed visual QA for selected shot outputs.

The vision model receives representative frames together with the shot's image
and video prompts.  It is deliberately advisory only when unavailable: a video
never gets an invented approval just because the QA provider is offline.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import frappe
import requests
from frappe.utils import now_datetime

from joymedia.services.vision_analysis import is_configured


QA_PROMPT = """You are a strict video-production QA reviewer. Inspect this contact sheet of the
first, middle, and last frames of one generated commercial video. Return JSON only:
{"reference_fidelity":0-100,"temporal_consistency":0-100,"prompt_adherence":0-100,
 "shot_continuity":0-100,"verdict":"Approved|Needs Revision",
 "rejection_category":"Motion Artifacts|Prompt Drift|Visual Quality|Continuity Break|Wrong Product|Other",
 "feedback_notes":"one short concrete reason"}
Score reference fidelity and product identity against the reference description, whether frames
are stable and preserve object/person identity, adherence to image/video prompts, and continuity
of the single shot. Approve only when every score is at least 75 and no visible severe defect.
"""


def run_automated_shot_review(shot_name, output_asset_version):
	"""Create one automated review for an immutable selected output.

	Returns ``None`` when vision QA is not configured or cannot inspect the local
	video. In either case the Shot remains Pending Review for a human reviewer.
	"""
	if not is_configured() or _already_reviewed(shot_name, output_asset_version):
		return None
	shot = frappe.get_doc("Shot", shot_name)
	try:
		result = _assess_video(shot, output_asset_version)
	except Exception:
		frappe.logger("joymedia.visual_qa").exception("Automated QA failed for Shot %s", shot_name)
		return None
	if not result:
		return None
	verdict = result["verdict"]
	generation_attempt = frappe.db.get_value(
		"Asset Version", output_asset_version, "source_generation_attempt"
	)
	review = frappe.get_doc({
		"doctype": "Shot Review",
		"shot": shot.name,
		"output_asset_version": output_asset_version,
		"generation_attempt": generation_attempt,
		"reviewer": frappe.session.user,
		"reviewed_at": now_datetime(),
		"verdict": verdict,
		"rejection_category": result.get("rejection_category") if verdict != "Approved" else None,
		"feedback_notes": result.get("feedback_notes"),
		"review_kind": "Automated",
		"quality_scores_json": json.dumps(result["scores"], sort_keys=True),
		"qa_model": frappe.conf.get("qwen_vl_model"),
	}).insert(ignore_permissions=True)
	# Never overwrite an explicit human decision.  A human review can be more
	# nuanced than frame sampling and remains the final override.
	latest_human = frappe.db.exists("Shot Review", {
		"shot": shot.name, "output_asset_version": output_asset_version, "review_kind": ["in", ["", "Human"]],
	})
	if not latest_human:
		frappe.db.set_value("Shot", shot.name, "review_status", verdict, update_modified=False)
	return review.name


def _already_reviewed(shot_name, output_asset_version):
	return frappe.db.exists("Shot Review", {
		"shot": shot_name, "output_asset_version": output_asset_version, "review_kind": "Automated",
	})


def _assess_video(shot, output_asset_version):
	path = _asset_version_path(output_asset_version)
	with tempfile.TemporaryDirectory(prefix="joymedia-visual-qa-") as directory:
		temporary = Path(directory)
		duration = _video_duration(path)
		frame_paths = []
		# Beginning/middle/end are necessary to detect identity drift and motion
		# artifacts that a single thumbnail cannot reveal.
		for index, timestamp in enumerate((0, max(0, duration / 2), max(0, duration - 0.05))):
			frame_path = temporary / f"frame-{index}.jpg"
			subprocess.run(
				["ffmpeg", "-y", "-ss", str(timestamp), "-i", str(path), "-frames:v", "1", "-vf", "scale=768:-2", str(frame_path)],
				check=True, capture_output=True,
			)
			frame_paths.append(frame_path)
		contact_sheet = temporary / "frames.jpg"
		_make_contact_sheet(frame_paths, contact_sheet)
		return _call_vision_qa(_file_data_url(contact_sheet), _reference_data_urls(shot), shot)


def _video_duration(path):
	probe = subprocess.run(
		["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
		check=True, capture_output=True, text=True,
	)
	return max(0.1, float(probe.stdout.strip()))


def _make_contact_sheet(frame_paths, destination):
	from PIL import Image
	frames = [Image.open(path).convert("RGB") for path in frame_paths]
	try:
		width = max(frame.width for frame in frames)
		height = max(frame.height for frame in frames)
		canvas = Image.new("RGB", (width * len(frames), height), "black")
		for index, frame in enumerate(frames):
			canvas.paste(frame, (index * width, 0))
		canvas.save(destination, format="JPEG", quality=88)
	finally:
		for frame in frames:
			frame.close()


def _asset_version_path(asset_version):
	file_url = frappe.db.get_value("Asset Version", asset_version, "file")
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	return Path(file_doc.get_full_path())


def _file_data_url(path):
	import base64
	return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _reference_data_urls(shot):
	"""Include the actual image ingredients when available, not just their prompt."""
	urls = []
	for reference in shot.get("references") or []:
		asset_version = reference.get("asset_version")
		if not asset_version:
			continue
		try:
			file_url = frappe.db.get_value("Asset Version", asset_version, "file")
			file_doc = frappe.get_doc("File", {"file_url": file_url})
			path = Path(file_doc.get_full_path())
			if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
				urls.append(_file_data_url(path))
		except Exception:
			frappe.logger("joymedia.visual_qa").warning("Unable to load reference %s for QA", asset_version)
		if len(urls) >= 4:
			break
	return urls


def _call_vision_qa(data_url, reference_urls, shot):
	base_url = frappe.conf.get("qwen_vl_base_url").rstrip("/")
	prompt = (
		f"REFERENCE / PRODUCT CONTEXT: {shot.get('image_prompt') or ''}\n"
		f"VIDEO PROMPT: {shot.get('generation_prompt') or ''}\n\n{QA_PROMPT}"
	)
	content = [{"type": "image_url", "image_url": {"url": url}} for url in reference_urls]
	content.append({"type": "image_url", "image_url": {"url": data_url}})
	content.append({"type": "text", "text": prompt})
	response = requests.post(
		f"{base_url}/chat/completions",
		json={"model": frappe.conf.get("qwen_vl_model"), "messages": [{"role": "user", "content": content}],
		      "response_format": {"type": "json_object"}, "temperature": 0.1, "max_tokens": 400},
		timeout=(10, float(frappe.conf.get("qwen_vl_timeout") or 120)),
	)
	response.raise_for_status()
	return normalize_visual_qa(json.loads(response.json()["choices"][0]["message"]["content"]))


def normalize_visual_qa(result):
	"""Validate model output; a malformed or over-optimistic response cannot pass QA."""
	if not isinstance(result, dict):
		raise ValueError("Visual QA response must be a JSON object")
	scores = {key: _score(result.get(key)) for key in (
		"reference_fidelity", "temporal_consistency", "prompt_adherence", "shot_continuity"
	)}
	model_verdict = str(result.get("verdict") or "").strip()
	approved = model_verdict == "Approved" and min(scores.values()) >= 75
	return {
		"scores": scores,
		"verdict": "Approved" if approved else "Needs Revision",
		"rejection_category": str(result.get("rejection_category") or "Visual Quality")[:80],
		"feedback_notes": str(result.get("feedback_notes") or "Automated visual QA requires revision.")[:1000],
	}


def _score(value):
	try:
		return max(0, min(100, round(float(value))))
	except (TypeError, ValueError):
		return 0
