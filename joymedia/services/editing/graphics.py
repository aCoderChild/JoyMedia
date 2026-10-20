"""Deterministic product-layer diagrams explicitly requested by a storyboard.

The generator animates the action; this small finishing primitive draws the exact
number of plies within one sheet. A model cannot be relied on to count thin layers correctly.
"""

import json
import math
import re
import subprocess


def layer_diagram_plan(text, seconds):
	if not math.isfinite(seconds) or seconds <= 0:
		return []
	text = str(text or "").casefold()
	if not re.search(r"graphic|illustrat|đồ họa", text):
		return []
	numbers = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
	match = re.search(r"\b(\d{1,2}|two|three|four|five|six|seven|eight)\s*(?:layers?|lớp)\b", text)
	if not match:
		return []
	count = numbers.get(match[1]) or int(match[1])
	if not 2 <= count <= 12 or seconds <= 0:
		return []
	standalone = bool(re.search(r"standalone|full.scene|whole scene|cảnh đồ họa riêng", text))
	result = {
		"type": "paper_layers",
		"layers": count,
		"start_seconds": 0 if standalone else max(0, seconds - 2),
		"duration_seconds": seconds if standalone else min(1, seconds),
	}
	if "lớp" in text:
		result["language"] = "vi"
	return [result]


def requested_graphics(source, beat_name, motion, seconds):
	"""Read editing intent from the client's source, independently of animation text.

	Older creative plans without source rows retain their explicit prompt-based
	insert. A matching imported row is authoritative: animation rewrites cannot
	silently drop a requested graphic or invent one the client never requested.
	"""
	if isinstance(source, str):
		try:
			source = json.loads(source)
		except ValueError:
			source = {}
	demo = source.get("selected_demo") if isinstance(source, dict) else None
	scenes = demo.get("scenes") if isinstance(demo, dict) else None
	matches = (
		[r for r in scenes if isinstance(r, dict) and r.get("beat_name") == beat_name]
		if isinstance(scenes, list)
		else []
	)
	if len(matches) > 1:
		raise ValueError("Graphic source has ambiguous scene names; use unique beat names.")
	if matches:
		motion = " ".join(str(matches[0].get(k) or "") for k in ("visual_camera", "action"))
	return layer_diagram_plan(motion, seconds)


def paper_layer_illustration(size, count, language="en", progress=1.0, highlight=None):
	"""Magnified cutaway of ONE laminated sheet with a shared bonded edge.

	Only its edge fans apart for inspection. These are constituent plies, not
	independent sheets or an asserted micrograph of the actual product.
	"""
	from pathlib import Path

	from PIL import Image, ImageDraw, ImageFont

	if type(count) is not int or not 2 <= count <= 12:
		raise ValueError("A sheet cutaway needs 2-12 plies")
	if type(progress) not in (int, float) or not math.isfinite(progress) or not 0 <= progress <= 1:
		raise ValueError("Cutaway progress must be between zero and one")
	if highlight is not None and (type(highlight) is not int or not 0 <= highlight < count):
		raise ValueError("Invalid constituent ply highlight")
	w, h = size
	image = Image.new("RGB", size, (237, 247, 250))
	draw = ImageDraw.Draw(image)
	unit = min(w, h)
	font_path = str(Path(__file__).parents[2] / "fonts" / "DejaVuSans-Bold.ttf")
	font = ImageFont.truetype(font_path, max(10, round(unit * 0.025)))
	label_font = ImageFont.truetype(font_path, max(10, round(unit * 0.034)))
	heading = ImageFont.truetype(font_path, max(14, round(unit * 0.055)))
	draw.text(
		(w * 0.5, h * 0.25),
		f"1 tờ / {count} lớp" if language == "vi" else f"1 sheet / {count} plies",
		fill=(25, 72, 93),
		font=heading,
		anchor="mm",
	)
	# One continuous tissue body with the same footprint and a shared edge.
	left, right, top = w * 0.10, w * 0.70, h * 0.43
	depth, fan = unit * 0.65, unit * min(0.042, 0.22 / count) * (0.12 + 0.88 * progress)
	body = [
		(left, top),
		(right, top - unit * 0.08),
		(right + depth * 0.35, top + depth * 0.55),
		(left + depth * 0.35, top + depth * 0.8),
	]
	draw.polygon([(x + 3, y + unit * 0.014) for x, y in body], fill=(195, 214, 221))
	draw.polygon(body, fill=(255, 255, 253), outline=(134, 163, 172), width=max(1, round(unit * 0.002)))
	for fibre in range(60):
		x = left + (right - left) * (fibre % 20 + 0.5) / 20
		y = top + depth * (0.12 + (fibre // 20) * 0.18) - unit * 0.08 * (x - left) / (right - left)
		draw.line((x, y, x + unit * 0.02, y - unit * 0.003), fill=(221, 230, 228), width=1)
	# The enlarged corner terminates in one joined seam; only the exposed edge
	# separates enough to count. Every ply remains connected to that seam.
	seam = (right - unit * 0.18, top + depth * 0.30)
	for index in range(count - 1, -1, -1):
		offset = (index - (count - 1) / 2) * fan
		points = [
			seam,
			(right + unit * 0.11, top + offset),
			(right + unit * 0.16, top + unit * 0.07 + offset),
			(seam[0], seam[1] + unit * 0.006),
		]
		draw.polygon(
			points,
			fill=(209, 241, 252)
			if index == highlight
			else (255 - index * 2, 255 - index * 2, 250 - index * 2),
			outline=(25, 124, 171) if index == highlight else (99, 145, 163),
			width=max(1, round(unit * (0.004 if index == highlight else 0.002))),
		)
		x, y = right + unit * 0.16, top + unit * 0.07 + offset
		draw.line((x, y, x + unit * 0.02, y), fill=(76, 124, 145), width=1)
		draw.text((x + unit * 0.035, y), str(index + 1), fill=(25, 72, 93), font=label_font, anchor="lm")
	draw.text(
		(w * 0.5, h * 0.83),
		"Minh họa phóng đại mép tờ giấy" if language == "vi" else "Magnified edge cutaway",
		fill=(70, 111, 128),
		font=font,
		anchor="mm",
	)
	return image


def apply_graphic_overlays(video, overlays, output, profile, frames):
	"""Insert an authored macro illustration, preserving exact frame count/audio."""
	import tempfile
	from pathlib import Path

	w, h, fps = profile["width"], profile["height"], profile["fps"]
	if not overlays:
		return video
	with tempfile.TemporaryDirectory() as folder:
		inputs, filters = [], []
		previous = "0:v"
		for index, overlay in enumerate(overlays, 1):
			if overlay.get("type") != "paper_layers":
				raise ValueError("Unsupported storyboard graphic")
			count = overlay["layers"]
			if type(count) is not int or not 2 <= count <= 12:
				raise ValueError("Layer diagram requires 2-12 layers")
			start_time, duration = overlay["start_seconds"], overlay["duration_seconds"]
			if (
				any(type(v) not in (int, float) or not math.isfinite(v) for v in (start_time, duration))
				or start_time < 0
				or duration <= 0
			):
				raise ValueError("Graphic timing must be finite and positive")
			start = round(start_time * fps)
			end = min(frames, start + max(1, round(duration * fps))) - 1
			if start > end:
				raise ValueError("Layer diagram is outside the scene")
			# Open the magnified edge, hold it legibly, then gently settle. Every
			# frame retains the same counted plies and their common bonded seam.
			length = end - start + 1
			for frame in range(frames):
				time = max(0, min(frame - start, length - 1)) / fps
				phase = min(1.0, time / max(0.1, min(1.5, duration * 0.4)))
				progress = phase * phase * (3 - 2 * phase)
				progress *= 1 - 0.035 * (1 - math.cos(time * 2 * math.pi / max(duration, 0.1)))
				highlight = (
					min(count - 1, int(max(0, time - duration * 0.3) / max(0.1, duration * 0.7) * count))
					if time >= duration * 0.3
					else None
				)
				paper_layer_illustration(
					(w, h), count, overlay.get("language", "en"), progress, highlight
				).save(Path(folder) / f"layers-{index}-{frame:05d}.png")
			inputs.extend(["-framerate", str(fps), "-i", str(Path(folder) / f"layers-{index}-%05d.png")])
			filters.append(
				f"[{previous}][{index}:v]overlay=0:0:enable='between(n,{start},{end})'[graphic{index}]"
			)
			previous = f"graphic{index}"
		subprocess.run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-i",
				str(video),
				*inputs,
				"-filter_complex",
				";".join(filters),
				"-map",
				f"[{previous}]",
				"-map",
				"0:a?",
				"-frames:v",
				str(frames),
				"-r",
				str(fps),
				"-c:v",
				"libx264",
				"-crf",
				"16",
				"-pix_fmt",
				"yuv420p",
				"-c:a",
				"copy",
				str(output),
			],
			check=True,
			capture_output=True,
			timeout=180,
		)
	return output
