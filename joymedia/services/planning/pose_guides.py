"""Plan a shot-specific COCO-18 guide and render it with CharacterPose's renderer.

The guide is a proposal, not evidence that the mascot achieved that pose.
The generated image is accepted only by the separate visual review in
``pose_assets``.
"""

import math
from pathlib import Path

from PIL import Image

from joymedia.workflow_adapters.vendor.characterpose.mixamo_tools.draw import draw_openpose
from joymedia.workflow_adapters.vendor.characterpose.mixamo_tools.mixamo_bones import COCO18_NAMES


def _validated_keypoints(raw):
	if not isinstance(raw, list) or len(raw) != len(COCO18_NAMES):
		raise ValueError("Pose guide must contain exactly 18 COCO joints.")
	points = []
	for point in raw:
		if not isinstance(point, list) or len(point) != 3:
			raise ValueError("Each pose joint needs x, y and visibility.")
		x, y, visible = point
		if any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
			raise ValueError("Pose joints must be finite numbers.")
		if not (0 <= x <= 1 and 0 <= y <= 1 and visible in (0, 1)):
			raise ValueError("Pose joint coordinates or visibility are invalid.")
		points.append([x, y, visible])
	# A guide without torso, head or any lower-body support is not actionable.
	if not all(points[i][2] for i in (0, 1, 2, 5, 8, 11)):
		raise ValueError("Pose guide is missing its visible head or torso.")
	if sum(bool(points[i][2]) for i in (9, 10, 12, 13)) < 2:
		raise ValueError("Pose guide is missing leg support.")
	return points


def plan_pose_guide(pose_description, angle, width, height):
	from joymedia.services.planning.production import _ask_planner

	if angle not in {"front", "side", "back"}:
		raise ValueError("Unsupported pose guide angle.")
	if min(width, height) < 256:
		raise ValueError("Pose guide dimensions are too small.")
	prompt = (
		"Draw ONE complete anthropomorphic character as a COCO-18 stick figure, "
		"on a black full-body canvas. Return 18 [x,y,visible] joints in this exact order: "
		+ ", ".join(COCO18_NAMES)
		+ ". Coordinates are normalized 0..1, origin top left; visible is 0 or 1. "
		"Plan visibly distinct limb articulation and physical weight support for: "
		+ pose_description
		+ ". Camera view: "
		+ angle
		+ ". "
		"For a side view, shoulders and hips may be close but keep both visible. "
		"Both feet or knees that bear weight must visibly reach the ground; raised paws must be above shoulders. "
		"No product, held prop or furniture. Do not copy the reference character's current pose."
	)
	result = _ask_planner(
		prompt,
		system="You produce physically coherent OpenPose COCO-18 keypoints for pose-conditioned image generation.",
		capability="planner",
		sampling_profile="production_plan",
		response_schema={
			"type": "object",
			"properties": {
				"keypoints": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}
			},
			"required": ["keypoints"],
			"additionalProperties": False,
		},
	)
	points = _validated_keypoints(result.get("keypoints"))
	return [[round(x * width), round(y * height), visible] for x, y, visible in points]


def render_pose_guide(pose_description, angle, width, height, destination):
	points = plan_pose_guide(pose_description, angle, width, height)
	path = Path(destination)
	Image.fromarray(draw_openpose(points, width=width, height=height)).save(path)
	return path
