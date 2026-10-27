"""Isolated SAM 2.1 image segmentation worker.

Run with a Python environment containing Meta's ``sam2`` package, torch,
numpy and Pillow. The Frappe worker supplies immutable input/output paths and
checks the returned metadata before admitting the cutout as reference media.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageFilter
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor


def background_box(image):
	"""Bound a subject only when the outer studio background is near-uniform."""
	pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
	height, width = pixels.shape[:2]
	band = max(2, min(height, width) // 20)
	border = np.concatenate(
		(
			pixels[:band].reshape(-1, 3),
			pixels[-band:].reshape(-1, 3),
			pixels[:, :band].reshape(-1, 3),
			pixels[:, -band:].reshape(-1, 3),
		)
	)
	background = np.median(border, axis=0)
	if float(np.percentile(np.max(np.abs(border - background), axis=1), 90)) > 20:
		raise ValueError("Automatic cutout needs a plain studio background or a verified subject box.")
	foreground = np.max(np.abs(pixels - background), axis=2) > 25
	y, x = np.where(foreground)
	if len(x) < width * height * 0.02:
		raise ValueError("Studio foreground is too small to segment reliably.")
	pad = max(4, round(min(width, height) * 0.01))
	return [
		max(0, int(x.min()) - pad),
		max(0, int(y.min()) - pad),
		min(width - 1, int(x.max()) + pad),
		min(height - 1, int(y.max()) + pad),
	], foreground


def cutout(input_path, output_path, checkpoint, box=None):
	from scipy.ndimage import binary_fill_holes, label

	image = Image.open(input_path).convert("RGB")
	pixels = np.asarray(image).copy()
	if box is None:
		box, foreground = background_box(image)
	else:
		foreground = None
	if len(box) != 4 or not (0 <= box[0] < box[2] < image.width and 0 <= box[1] < box[3] < image.height):
		raise ValueError("Subject box must fit inside the source image.")
	model = build_sam2("configs/sam2.1/sam2.1_hiera_t.yaml", checkpoint, device="cpu")
	predictor = SAM2ImagePredictor(model)
	with torch.inference_mode():
		predictor.set_image(pixels)
		masks, scores, _ = predictor.predict(box=np.asarray(box), multimask_output=True)
	options = []
	diagnostics = []
	for mask, score in zip(masks, scores, strict=True):
		# SAM 2 can mistake white printing on a pale package for the white
		# studio background. Printing inside the connected object stays opaque.
		mask = binary_fill_holes(mask)
		parts, count = label(mask)
		sizes = np.bincount(parts.ravel())[1:] if count else np.array([])
		main = int(sizes.max()) if len(sizes) else 0
		connected = main / max(1, int(mask.sum()))
		# A studio drop shadow may be a small detached component. Keep the
		# actual object, then measure retention against the source foreground.
		if count and connected >= 0.95:
			mask = binary_fill_holes(parts == int(sizes.argmax()) + 1)
		coverage = float(mask.mean())
		foreground_retained = float(mask[foreground].mean()) if foreground is not None else None
		contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
		outline = max(contours, key=cv2.contourArea) if contours else None
		hull_length = cv2.arcLength(cv2.convexHull(outline), True) if outline is not None else 0
		edge_roughness = cv2.arcLength(outline, True) / hull_length if hull_length else float("inf")
		diagnostics.append(
			(
				round(float(score), 3),
				round(coverage, 3),
				round(connected, 3),
				round(foreground_retained, 3) if foreground_retained is not None else None,
				round(edge_roughness, 3),
			)
		)
		if not 0.02 < coverage < 0.85:
			continue
		if connected < 0.98:
			continue
		# The studio foreground threshold also sees cast shadows. A clean mask
		# should keep the object, while excluding up to 15% of such shadow pixels.
		if foreground_retained is not None and foreground_retained < 0.85:
			continue
		# Studio shadows and pale backdrops often cling to the object at a few
		# pixels. SAM 2 may score such a ragged mask higher than a clean alternate.
		# A bounded contour/hull ratio rejects those fringes without repainting RGB.
		if edge_roughness > 1.25:
			continue
		options.append((float(score), mask, coverage, edge_roughness))
	if not options or max(score for score, _, _, _ in options) < 0.75:
		raise ValueError(
			"No connected high-confidence subject mask retained the studio foreground; "
			+ f"(score, area, connected, foreground, edge)={diagnostics}"
		)
	score, mask, coverage, edge_roughness = max(options, key=lambda item: item[0] - 0.3 * (item[3] - 1))
	alpha = Image.fromarray((mask.astype(np.uint8) * 255), "L").filter(ImageFilter.GaussianBlur(0.6))
	output = Image.merge("RGBA", (*image.split(), alpha))
	output.save(output_path, "PNG")
	return {
		"backend": "sam2.1_hiera_tiny",
		"score": round(score, 4),
		"foreground_fraction": round(coverage, 4),
		"edge_roughness": round(edge_roughness, 4),
		"box": box,
		"source_width": image.width,
		"source_height": image.height,
	}


if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("input")
	parser.add_argument("output")
	parser.add_argument("checkpoint")
	parser.add_argument("--box", type=json.loads)
	args = parser.parse_args()
	print(json.dumps(cutout(Path(args.input), Path(args.output), args.checkpoint, args.box)))
