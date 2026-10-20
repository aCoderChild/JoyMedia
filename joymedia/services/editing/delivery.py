"""Optional immutable-workflow delivery transform; no interpolation or inferred FPS."""

import math


def delivery_contract(workflow):
	from joymedia.services.workflows.capabilities import execution_spec

	value = execution_spec(workflow).get("delivery")
	if value is None:
		return None
	allowed = {
		"width",
		"height",
		"fps",
		"audio_sample_rate",
		"audio_channels",
		"crf",
		"preset",
		"sharpen",
		"contrast",
		"brightness",
		"saturation",
	}
	if not isinstance(value, dict) or set(value) - allowed:
		raise ValueError("Unsupported workflow delivery fields.")
	result = {
		"crf": 14,
		"preset": "slow",
		"sharpen": 0,
		"contrast": 1,
		"brightness": 0,
		"saturation": 1,
		"audio_sample_rate": 44100,
		"audio_channels": 2,
		**value,
	}
	for key in ["width", "height"]:
		if type(result.get(key)) is not int or not 32 <= result[key] <= 3840 or result[key] % 2:
			raise ValueError("Delivery dimensions must be even integers from 32 to 3840.")
	for key, low, high in [
		("fps", 1, 120),
		("crf", 0, 51),
		("sharpen", 0, 1),
		("contrast", 0.8, 1.2),
		("brightness", -0.1, 0.1),
		("saturation", 0.8, 1.2),
	]:
		x = result.get(key)
		if type(x) not in (int, float) or not math.isfinite(x) or not low <= x <= high:
			raise ValueError("Invalid delivery " + key)
	if (
		result["preset"] not in {"medium", "slow"}
		or result["audio_sample_rate"] not in {44100, 48000}
		or result["audio_channels"] not in {1, 2}
	):
		raise ValueError("Unsupported delivery encoder/audio settings.")
	return result


def transform_delivery(source, target, profile, contract):
	from joymedia.services.editing.composer import _run_ffmpeg

	if abs(float(contract["fps"]) - float(profile["fps"])) > 0.001:
		raise ValueError("Delivery transforms preserve native FPS; interpolation is not enabled.")
	filters = [f"scale={contract['width']}:{contract['height']}:flags=lanczos+accurate_rnd+full_chroma_int"]
	if contract["sharpen"]:
		filters.append(f"unsharp=5:5:{contract['sharpen']}:5:5:0.0")
	if (contract["contrast"], contract["brightness"], contract["saturation"]) != (1, 0, 1):
		filters.append(
			f"eq=contrast={contract['contrast']}:brightness={contract['brightness']}:saturation={contract['saturation']}"
		)
	_run_ffmpeg(
		[
			"ffmpeg",
			"-y",
			"-i",
			str(source),
			"-map",
			"0:v:0",
			"-map",
			"0:a?",
			"-vf",
			",".join(filters),
			"-c:v",
			"libx264",
			"-crf",
			str(contract["crf"]),
			"-preset",
			contract["preset"],
			"-pix_fmt",
			"yuv420p",
			"-c:a",
			"aac",
			"-b:a",
			"320k",
			"-ar",
			str(contract["audio_sample_rate"]),
			"-ac",
			str(contract["audio_channels"]),
			"-movflags",
			"+faststart",
			str(target),
		]
	)
	return {**profile, "width": contract["width"], "height": contract["height"]}
