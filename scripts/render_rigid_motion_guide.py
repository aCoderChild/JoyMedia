#!/usr/bin/env python3
"""Render a bounded rigid-body previs from JSON (optional pymunk extra).

This is a staging tool, not a fluid solver or final commercial renderer. Circle
particles can illustrate a material trajectory; they do not model absorption,
surface tension or a continuous liquid. Use the rendered clip as a motion guide.
Only local, operator-authored JSON is accepted; this is not a public RPC.
"""

import argparse
import hashlib
import json
import math
import subprocess
from itertools import pairwise
from pathlib import Path


def render(scene, output):
	import pymunk
	from PIL import Image, ImageDraw

	width, height, fps, frames = (int(scene[k]) for k in ("width", "height", "fps", "frames"))
	if not (16 <= width <= 1920 and 16 <= height <= 1920 and 1 <= fps <= 60 and 1 <= frames <= 240):
		raise ValueError("Previs exceeds the raster or time budget")
	entities = scene.get("bodies", [])
	if not isinstance(entities, list) or not 1 <= len(entities) <= 128:
		raise ValueError("Previs needs 1-128 bodies")
	space = pymunk.Space()
	space.gravity = tuple(scene.get("gravity", [0, 900]))
	space.iterations = 30
	bodies, shapes = {}, {}
	for entity in entities:
		name = entity["id"]
		if name in bodies:
			raise ValueError("Previs body identifiers must be unique")
		kind = entity.get("type", "static")
		if kind not in {"static", "dynamic", "kinematic"}:
			raise ValueError("Unsupported body type")
		body = pymunk.Body(
			entity.get("mass", 1),
			entity.get("moment", 1000),
			body_type={
				"static": pymunk.Body.STATIC,
				"dynamic": pymunk.Body.DYNAMIC,
				"kinematic": pymunk.Body.KINEMATIC,
			}[kind],
		)
		body.position = tuple(entity["position"])
		body.angle = float(entity.get("angle", 0))
		space.add(body)
		bodies[name], shapes[name] = body, []
		for geometry in entity.get("shapes", []):
			if geometry["kind"] == "circle":
				shape = pymunk.Circle(body, geometry["radius"], tuple(geometry.get("offset", [0, 0])))
			elif geometry["kind"] == "segment":
				shape = pymunk.Segment(
					body, tuple(geometry["a"]), tuple(geometry["b"]), geometry.get("radius", 2)
				)
			elif geometry["kind"] == "polygon":
				shape = pymunk.Poly(body, geometry["vertices"])
			else:
				raise ValueError("Unsupported geometry")
			shape.friction = entity.get("friction", 0.6)
			shape.elasticity = entity.get("elasticity", 0.02)
			shape.sensor = bool(entity.get("sensor", False))
			space.add(shape)
			shapes[name].append((shape, geometry))
	process = subprocess.Popen(
		[
			"ffmpeg",
			"-v",
			"error",
			"-y",
			"-f",
			"rawvideo",
			"-pix_fmt",
			"rgb24",
			"-s",
			f"{width}x{height}",
			"-r",
			str(fps),
			"-i",
			"-",
			"-an",
			"-c:v",
			"libx264",
			"-crf",
			"15",
			"-pix_fmt",
			"yuv420p",
			str(output),
		],
		stdin=subprocess.PIPE,
		stderr=subprocess.PIPE,
	)
	trajectories = []
	try:
		for frame in range(frames):
			time = frame / fps
			for entity in entities:
				if not entity.get("path"):
					continue
				if entity.get("type") != "kinematic":
					raise ValueError("Only kinematic bodies accept authored paths")
				body = bodies[entity["id"]]
				points = entity["path"]
				if any(b[0] <= a[0] for a, b in pairwise(points)):
					raise ValueError("Driver times must increase")
				a, b = points[0], points[-1]
				for first, last in pairwise(points):
					if first[0] <= time <= last[0]:
						a, b = first, last
						break
				weight = max(0, min(1, (time - a[0]) / max(1e-9, b[0] - a[0])))
				target = pymunk.Vec2d(a[1] + weight * (b[1] - a[1]), a[2] + weight * (b[2] - a[2]))
				body.velocity = (target - body.position) * fps
			image = Image.new("RGB", (width, height), scene.get("background", "#eedbc6"))
			draw = ImageDraw.Draw(image)
			for entity in entities:
				name = entity["id"]
				body = bodies[name]
				for shape, geometry in shapes[name]:
					color = geometry.get("color", entity.get("color", "#ceb18d"))
					if isinstance(shape, pymunk.Circle):
						point = body.local_to_world(shape.offset)
						r = shape.radius
						draw.ellipse((point.x - r, point.y - r, point.x + r, point.y + r), fill=color)
					elif isinstance(shape, pymunk.Segment):
						draw.line(
							[tuple(body.local_to_world(p)) for p in [shape.a, shape.b]],
							fill=color,
							width=max(1, round(shape.radius * 2)),
						)
					else:
						draw.polygon(
							[tuple(body.local_to_world(p)) for p in shape.get_vertices()], fill=color
						)
				if entity.get("connected_to"):
					anchor = bodies[entity["connected_to"]].position
					draw.line(
						[tuple(anchor), tuple(body.position)],
						fill=entity.get("color", "#eadbc0"),
						width=entity.get("link_width", 24),
					)
			process.stdin.write(image.tobytes())
			trajectories.append(
				{
					"frame": frame,
					"bodies": {
						name: {"position": list(body.position), "angle": body.angle}
						for name, body in bodies.items()
					},
				}
			)
			for _ in range(12):
				space.step(1 / (fps * 12))
	finally:
		process.stdin.close()
		errors = process.stderr.read().decode()
		if process.wait():
			raise RuntimeError(errors)
	return {
		"scene_sha256": hashlib.sha256(json.dumps(scene, sort_keys=True).encode()).hexdigest(),
		"pymunk_version": pymunk.version,
		"trajectories": trajectories,
	}


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("scene", type=Path)
	parser.add_argument("output", type=Path)
	args = parser.parse_args()
	scene = json.loads(args.scene.read_text())
	if any(not math.isfinite(value) for value in [scene[k] for k in ("width", "height", "fps", "frames")]):
		raise ValueError("Scene dimensions and time must be finite")
	result = render(scene, args.output)
	args.output.with_suffix(".trajectory.json").write_text(json.dumps(result))


if __name__ == "__main__":
	main()
