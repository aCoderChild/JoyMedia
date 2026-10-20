"""Deterministic, lossless framing of semantic references for any image workflow."""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from pathlib import Path

ROLE_ALIASES = {
	"people": "person",
	"person": "person",
	"character": "character",
	"talent": "person",
	"product": "product",
	"product_reference": "product",
	"product_1": "product",
	"product_2": "product_2",
	"environment": "environment",
	"place": "environment",
	"background": "environment",
	"reference_board": "general",
}


def normalize_reference_role(value):
	key = str(value or "general").strip().lower().replace(" ", "_")
	return ROLE_ALIASES.get(key, key or "general")


def compose_reference_board(references, *, width=1344, height=768):
	"""Return a stable PNG board and a prompt instruction describing its tiles.

	Each reference is fitted into a deterministic grid. The board is deliberately
	plain and unlabelled: role information is passed in the prompt so Flux does not
	learn to reproduce UI labels or filenames in the generated frame.
	"""
	if not references:
		raise ValueError("At least one reference is required")

	try:
		from PIL import Image, ImageOps
	except ImportError as exc:  # pragma: no cover - deployment dependency failure
		raise RuntimeError("Pillow is required for local multi-reference composition") from exc

	items = []
	for reference in references:
		path = Path(reference["path"])
		if not path.exists():
			raise FileNotFoundError(path)
		role = normalize_reference_role(reference.get("role"))
		label = str(reference.get("label") or "").strip()
		data = path.read_bytes()
		with Image.open(path) as source:
			oriented = ImageOps.exif_transpose(source).convert("RGBA")
			image = Image.new("RGB", oriented.size, "white")
			image.paste(oriented, mask=oriented.getchannel("A"))
		items.append(
			{"image": image, "role": role, "label": label, "digest": hashlib.sha256(data).hexdigest()}
		)

	# Stable ordering preserves the user's selected-reference order, while the
	# digest makes identical input bytes produce the same board and cache name.
	width, height = max(256, int(width)), max(256, int(height))
	cols = max(1, math.ceil(math.sqrt(len(items) * width / height)))
	rows = math.ceil(len(items) / cols)
	gap = max(8, round(min(width, height) * 0.012))
	tile_width = max(1, (width - gap * (cols + 1)) // cols)
	tile_height = max(1, (height - gap * (rows + 1)) // rows)
	board = Image.new("RGB", (width, height), (238, 238, 238))
	for index, item in enumerate(items):
		column, row = index % cols, index // cols
		x = gap + column * (tile_width + gap)
		y = gap + row * (tile_height + gap)
		# Contain every source edge: cropping can remove ears, paw markings or
		# packaging print and changes the identity before the model sees it.
		fitted = ImageOps.pad(
			item["image"], (tile_width, tile_height), method=Image.Resampling.LANCZOS, color="white"
		)
		board.paste(fitted, (x, y))

	digest_input = (
		"|".join(f"{item['role']}:{item['digest']}" for item in items)
		+ f"|{width}x{height}|{cols}x{rows}|contain-white-v2"
	)
	digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
	output_dir = Path("/tmp/joymedia-reference-boards")
	output_dir.mkdir(parents=True, exist_ok=True)
	output_path = output_dir / f"reference-board-{digest}.png"
	if not output_path.exists():
		with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".png", delete=False) as temporary:
			try:
				board.save(temporary, format="PNG", optimize=False, compress_level=9)
				temporary.close()
				os.replace(temporary.name, output_path)
			finally:
				Path(temporary.name).unlink(missing_ok=True)

	placements = []
	for index, item in enumerate(items, start=1):
		column, row = (index - 1) % cols, (index - 1) // cols
		position = ("top" if row == 0 else "bottom") + "-" + ("left" if column == 0 else "right")
		placements.append(f"tile {index} ({position}) is the {item['role']} reference")
	instruction = (
		"Reference board guidance: preserve the identity and material details from the "
		+ "; ".join(placements)
		+ ". Use the board as a combined visual reference, but compose one coherent scene. Each tile is independently fitted: its image size does not imply physical scale. Follow the authored scene proportions and support surfaces."
	)
	return {"path": str(output_path), "sha256": digest, "instruction": instruction, "count": len(items)}
