"""Thin Comfy adapter around pinned upstream matting and open-set detection.

The generative model chooses staging. This node replaces a uniquely detected,
unoccluded product with original RGB artwork. It never generates a new label.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import folder_paths
import numpy as np
import torch
from PIL import Image, ImageOps


def configuration():
	path = Path(os.environ["JOYMEDIA_RETENTION_MANIFEST"])
	config = json.loads(path.read_text())
	root = Path(config["storage_root"]).resolve()
	if root.stat().st_dev == Path("/").stat().st_dev:
		raise ValueError("Reference models must be on the large mounted volume.")
	for key in ("repository", "cache"):
		if not Path(config[key]).resolve().is_relative_to(root):
			raise ValueError("Reference runtime paths must stay on the large volume.")
	code = hashlib.sha256(
		b"".join(Path(__file__).with_name(n).read_bytes() for n in ["__init__.py", "worker.py"])
	).hexdigest()
	if config.get("adapter_sha256") != code:
		raise ValueError("Reference adapter differs from its pinned recipe.")
	return config


class RetainReference:
	@classmethod
	def INPUT_TYPES(cls):
		return {"required": {"image": ("IMAGE",), "source_image": ("STRING",), "recipe_sha256": ("STRING",)}}

	RETURN_TYPES = ()
	FUNCTION = "run"
	OUTPUT_NODE = True
	CATEGORY = "JoyMedia/References"

	def run(self, image, source_image, recipe_sha256):
		config = configuration()
		actual = hashlib.sha256(
			json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
		).hexdigest()
		if actual != recipe_sha256:
			raise ValueError("The deployed reference recipe differs from the frozen request.")
		input_root = Path(folder_paths.get_input_directory()).resolve()
		path = (input_root / source_image).resolve()
		if not path.is_relative_to(input_root):
			raise ValueError("Reference must be a staged input image.")
		import subprocess
		import tempfile

		output = Path(folder_paths.get_output_directory())
		output.mkdir(parents=True, exist_ok=True)
		pixels = np.rint(image[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
		key = hashlib.sha256(pixels.tobytes() + path.read_bytes() + actual.encode()).hexdigest()
		scene_output, patch_output = (
			output / f"retained-{key}-scene.png",
			output / f"retained-{key}-source-patch.png",
		)
		with tempfile.TemporaryDirectory(prefix="retention-", dir=output) as temporary:
			scene_path = Path(temporary) / "scene.png"
			evidence_path = Path(temporary) / "evidence.json"
			Image.fromarray(pixels).convert("RGB").save(scene_path, "PNG")
			result = subprocess.run(
				[
					sys.executable,
					str(Path(__file__).with_name("worker.py")),
					str(path),
					str(scene_path),
					str(scene_output),
					str(patch_output),
					str(evidence_path),
				],
				timeout=300,
				capture_output=True,
				text=True,
			)
			if result.returncode:
				raise ValueError("Reference preparation worker failed: " + result.stderr[-1800:])
			evidence = json.loads(evidence_path.read_text())
		evidence["recipe_sha256"] = actual
		return {
			"ui": {
				"images": [
					{"filename": f.name, "subfolder": "", "type": "output"}
					for f in [scene_output, patch_output]
				],
				"retention": [evidence],
			}
		}


NODE_CLASS_MAPPINGS = {"JoyMediaRetainReference": RetainReference}
NODE_DISPLAY_NAME_MAPPINGS = {"JoyMediaRetainReference": "Retain original reference artwork"}
