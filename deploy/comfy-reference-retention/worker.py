"""Isolated process for upstream packages with generic module names."""

import bisect
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

_MODELS = {}
VOCABULARY = "box . package . bottle . jar . vase . cup . plate . chair . toy . bag . tube . can . lipstick . cosmetics ."


def configuration():
	path = Path(os.environ["JOYMEDIA_RETENTION_MANIFEST"])
	config = json.loads(path.read_text())
	root = Path(config["storage_root"]).resolve()
	if root.stat().st_dev == Path("/").stat().st_dev:
		raise ValueError("Reference models must be on the large mounted volume.")
	for key in ("repository", "cache"):
		if not Path(config[key]).resolve().is_relative_to(root):
			raise ValueError("Reference runtime paths must stay on the large volume.")
	return config


def models(config):
	if not _MODELS:
		from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

		sys.path.insert(0, config["repository"])
		from models.birefnet import BiRefNet

		common = dict(cache_dir=config["cache"], local_files_only=True)
		_MODELS["matte"] = BiRefNet.from_pretrained(
			config["matte_model"], revision=config["matte_revision"], bb_pretrained=False, **common
		).eval()
		_MODELS["detector"] = AutoModelForZeroShotObjectDetection.from_pretrained(
			config["detector_model"], revision=config["detector_revision"], **common
		).eval()
		_MODELS["processor"] = AutoProcessor.from_pretrained(
			config["detector_model"], revision=config["detector_revision"], **common
		)
	return _MODELS


def detect(image, caption, runtime, threshold=0.30, atomic_categories=False):
	processor, detector = runtime["processor"], runtime["detector"]
	device = "cuda"
	detector.to(device)
	try:
		inputs = processor(images=image, text=caption, return_tensors="pt").to(device)
		with torch.inference_mode():
			output = detector(**inputs)
		result = processor.post_process_grounded_object_detection(
			output,
			inputs.input_ids,
			threshold=threshold,
			text_threshold=0.25,
			target_sizes=[image.size[::-1]],
		)[0]
		from torchvision.ops import nms

		indices = nms(result["boxes"], result["scores"], 0.45).tolist()
		# GroundingDINO's upstream predict(remove_combined=True) confines a
		# phrase to the period-delimited class containing its highest logit.
		# HF's unrestricted labels can combine "package jar", making a glass
		# an unintended second target when that phrase is used for scene search.
		# Adapted from IDEA-Research/GroundingDINO util/inference.py at
		# 856dde20aee659246248e20734ef9ba5214f5e44 (Apache-2.0).
		labels = result.get("text_labels", result.get("labels"))
		if atomic_categories:
			probabilities = output.logits.sigmoid()[0]
			probabilities = probabilities[probabilities.max(dim=-1).values > threshold]
			token_ids = inputs.input_ids[0].tolist()
			separators = {
				processor.tokenizer.cls_token_id,
				processor.tokenizer.sep_token_id,
				processor.tokenizer.convert_tokens_to_ids("."),
			}
			boundaries = [i for i, token in enumerate(token_ids) if token in separators]
			label_ids = []
			for probability in probabilities:
				peak = int(probability.argmax())
				position = bisect.bisect_left(boundaries, peak)
				if not 0 < position < len(boundaries):
					raise ValueError("Detected object has no bounded category phrase.")
				left, right = boundaries[position - 1], boundaries[position]
				label_ids.append([token_ids[i] for i in range(left + 1, right) if probability[i] > 0.25])
			labels = processor.tokenizer.batch_decode(label_ids, skip_special_tokens=True)
			if any(not label.strip() for label in labels):
				raise ValueError("Detected object category is empty; do not guess placement.")
		return [
			dict(
				box=result["boxes"][i].cpu().tolist(), score=float(result["scores"][i]), label=str(labels[i])
			)
			for i in indices
		]
	finally:
		detector.to("cpu")


def alpha(image, runtime):
	from torchvision import transforms

	model = runtime["matte"].to("cuda")
	transform = transforms.Compose(
		[
			transforms.Resize((1024, 1024)),
			transforms.ToTensor(),
			transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
		]
	)
	try:
		with torch.inference_mode():
			mask = model(transform(image).unsqueeze(0).to("cuda"))[-1].sigmoid().cpu()[0].squeeze()
		return transforms.ToPILImage()(mask).resize(image.size, Image.Resampling.LANCZOS)
	finally:
		model.to("cpu")


def overlap(a, b):
	return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def prepare(source, scene, config):
	runtime = models(config)
	rgba = source.convert("RGBA")
	if rgba.getchannel("A").getextrema()[0] == 255:
		rgba.putalpha(alpha(source.convert("RGB"), runtime))
	mask = np.asarray(rgba.getchannel("A"))
	foreground = mask > 128
	fraction = float(foreground.mean())
	if not 0.02 < fraction < 0.95:
		raise ValueError("Source matte is empty or includes almost the entire photograph.")
	bounds = rgba.getchannel("A").point(lambda x: 255 if x > 16 else 0).getbbox()
	if not bounds:
		raise ValueError("Source object is not visible.")
	area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
	candidates = detect(source.convert("RGB"), VOCABULARY, runtime, 0.22, atomic_categories=True)
	candidates = [r for r in candidates if overlap(r["box"], bounds) / area > 0.65]
	if not candidates:
		raise ValueError("Source category is uncertain; do not guess product placement.")
	category = max(candidates, key=lambda r: r["score"])["label"]
	source_box = max(candidates, key=lambda r: r["score"])["box"]
	for limb in detect(source.convert("RGB"), "hand . arm .", runtime, 0.28):
		intersection = overlap(limb["box"], source_box)
		limb_area = max(1, (limb["box"][2] - limb["box"][0]) * (limb["box"][3] - limb["box"][1]))
		if intersection / max(1, area) > 0.06 and intersection / limb_area < 0.85:
			raise ValueError("Source reference is physically occluded; an isolated product view is required.")

	found = detect(scene, category + " .", runtime)
	if len(found) != 1:
		raise ValueError(f"Expected one unambiguous product; detected {len(found)}.")
	box = found[0]["box"]
	x1, y1, x2, y2 = box
	sw, sh = bounds[2] - bounds[0], bounds[3] - bounds[1]
	if min(x1, y1) < 1 or x2 >= scene.width - 1 or y2 >= scene.height - 1:
		raise ValueError("Product is cropped at the scene edge.")
	if abs(np.log(((x2 - x1) / (y2 - y1)) / (sw / sh))) > 0.40:
		raise ValueError("Product view is incompatible with the supplied source photograph.")
	for limb in detect(scene, "hand . paw . arm .", runtime, 0.28):
		intersection = overlap(limb["box"], box)
		limb_area = max(1, (limb["box"][2] - limb["box"][0]) * (limb["box"][3] - limb["box"][1]))
		if intersection / max(1, (x2 - x1) * (y2 - y1)) > 0.06 and intersection / limb_area < 0.85:
			raise ValueError("Product overlaps a limb; an occlusion-aware workflow is required.")
	# Cover the proposed footprint with the original view without stretching it.
	scale = max((x2 - x1) / sw, (y2 - y1) / sh)
	w, h = round(sw * scale), round(sh * scale)
	x, y = round((x1 + x2 - w) / 2), round(y2 - h)
	if x < 0 or y < 0 or x + w > scene.width or y + h > scene.height:
		raise ValueError("Original source cannot fit the detected footprint.")
	patch = rgba.crop(bounds).resize((w, h), Image.Resampling.LANCZOS)
	# No luminance tint, inpainting or generative repaint touches source RGB.
	import cv2

	# Segment only the generated object with the already pinned BiRefNet.
	# A rectangular erase destroys its contact shadow and supporting surface.
	crop_box = (
		max(0, int(x1) - 8),
		max(0, int(y1) - 8),
		min(scene.width, int(np.ceil(x2)) + 8),
		min(scene.height, int(np.ceil(y2)) + 8),
	)
	object_alpha = alpha(scene.crop(crop_box), runtime)
	object_mask = (np.asarray(object_alpha) > 128).astype(np.uint8) * 255
	if not 0.02 < float((object_mask > 0).mean()) < 0.98:
		raise ValueError("Scene product matte is uncertain; do not erase its supporting surface.")
	object_mask = cv2.dilate(object_mask, np.ones((3, 3), np.uint8))
	removal = np.zeros((scene.height, scene.width), dtype=np.uint8)
	removal[crop_box[1] : crop_box[3], crop_box[0] : crop_box[2]] = object_mask
	clean = cv2.inpaint(np.asarray(scene), removal, 7, cv2.INPAINT_TELEA)
	composed = Image.fromarray(clean).convert("RGBA")
	composed.alpha_composite(patch, (x, y))
	return (
		composed.convert("RGB"),
		patch,
		dict(
			background_reconstruction="opencv_telea_within_birefnet_object_matte",
			box=[x, y, w, h],
			category=category,
			detections=found,
			source_rgb_unchanged=rgba.convert("RGB").tobytes() == source.convert("RGB").tobytes(),
			matte_fraction=fraction,
		),
	)


if __name__ == "__main__":
	source_path, scene_path, output_path, patch_path, evidence_path = map(Path, sys.argv[1:])
	config = configuration()
	with Image.open(source_path) as original:
		source = ImageOps.exif_transpose(original).convert("RGBA")
	with Image.open(scene_path) as original:
		scene = original.convert("RGB")
	composed, patch, evidence = prepare(source, scene, config)
	composed.save(output_path, "PNG")
	patch.save(patch_path, "PNG")
	evidence.update(
		source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
		repositories=config["repositories"],
	)
	evidence_path.write_text(json.dumps(evidence))
