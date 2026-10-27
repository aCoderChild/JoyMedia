"""Validated exact-pixel cutouts for studio character and product references.

The independent SAM 2 worker only supplies alpha. It cannot redraw, recolour,
rescale or alter printed artwork. Inconclusive masks remain unavailable rather
than entering the storyboard as trustworthy reference media.
"""

import hashlib
import io
import json
import subprocess
import tempfile
from pathlib import Path

import frappe


def edge_roughness(image):
	"""Perimeter excess over the visible silhouette's convex hull.

	Large excess on studio subjects is a reliable sign of retained backdrop or
	shadow fragments, even when a vision caption calls the cutout clean.
	"""
	import cv2
	import numpy as np

	mask = (np.asarray(image.convert("RGBA").getchannel("A")) > 128).astype(np.uint8)
	contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
	if not contours:
		return float("inf")
	outline = max(contours, key=cv2.contourArea)
	hull = cv2.arcLength(cv2.convexHull(outline), True)
	return cv2.arcLength(outline, True) / hull if hull else float("inf")


def sam2_configured():
	return bool(frappe.conf.get("joymedia_sam2_python") and frappe.conf.get("joymedia_sam2_checkpoint"))


def cutout_studio_reference(content):
	"""Return a transparent PNG plus mask evidence, or raise on uncertain output."""
	from PIL import Image, ImageChops

	python = Path(frappe.conf.get("joymedia_sam2_python") or "")
	checkpoint = Path(frappe.conf.get("joymedia_sam2_checkpoint") or "")
	if not python.is_file() or not checkpoint.is_file():
		raise ValueError("SAM 2 cutout worker and checkpoint are not configured.")
	worker = Path(__file__).with_name("sam2_cutout_cli.py")
	with tempfile.TemporaryDirectory(prefix="joymedia-cutout-") as folder:
		root = Path(folder)
		input_path, output_path = root / "input.png", root / "output.png"
		input_path.write_bytes(content)
		result = subprocess.run(
			[str(python), str(worker), str(input_path), str(output_path), str(checkpoint)],
			capture_output=True,
			text=True,
			timeout=180,
			check=False,
		)
		if result.returncode:
			raise ValueError(
				"SAM 2 could not establish a reliable foreground mask: "
				+ (result.stderr or result.stdout).strip()[-300:]
			)
		evidence = json.loads(result.stdout.strip().splitlines()[-1])
		with Image.open(io.BytesIO(content)) as original, Image.open(output_path) as masked:
			if masked.mode != "RGBA" or masked.size != original.size:
				raise ValueError("Cutout dimensions or alpha channel differ from source.")
			if ImageChops.difference(original.convert("RGB"), masked.convert("RGB")).getbbox():
				raise ValueError("Cutout changed source colours or artwork.")
			if masked.getchannel("A").getextrema() != (0, 255):
				raise ValueError("Cutout has no useful foreground and background separation.")
			roughness = edge_roughness(masked)
			if roughness > 1.25:
				raise ValueError(f"Cutout outline retains studio fragments (roughness {roughness:.3f}).")
			evidence["edge_roughness"] = round(roughness, 4)
			from joymedia.services.review.consistency import ask

			# A connected mask can still retain a white studio shadow or ragged
			# background attached to a pale subject. Inspect it against a dark
			# ground before admitting it as exact artwork for scene compositing.
			ground = Image.new("RGBA", masked.size, (45, 45, 45, 255))
			ground.alpha_composite(masked)
			preview = io.BytesIO()
			ground.convert("RGB").save(preview, "PNG")
			quality = ask(
				preview.getvalue(),
				"This is a studio subject cutout shown on dark gray. Judge only mask quality: "
				"does the visible subject form a clean single silhouette without detached white "
				"studio scraps, attached floor/shadow patches, missing internal artwork, "
				"or a large pale halo? The subject itself may contain white fur or packaging. "
				"Return JSON clean boolean or null, and reason string. Answer null when unsure.",
				max_edge=768,
			)
			if quality.get("clean", quality.get("mask_quality")) is not True:
				raise ValueError(
					"Cutout edge or retained artwork needs review: "
					+ str(quality.get("reason") or "uncertain mask")[:200]
				)
			evidence["visual_mask_review"] = {"clean": True, "reason": str(quality.get("reason") or "")[:200]}
		return output_path.read_bytes(), evidence


def ensure_transparent_reference(project, row):
	"""Add an immutable, exact-colour cutout of one selected studio reference."""
	from PIL import Image

	from joymedia.services.intake.assets import create_media_asset
	from joymedia.services.project.reference_lineage import lineage_identity

	version = frappe.get_doc("Asset Version", row.asset_version)
	path = Path(frappe.get_doc("File", {"file_url": version.file}).get_full_path())
	with Image.open(path) as image:
		if image.convert("RGBA").getchannel("A").getextrema()[0] < 255:
			if edge_roughness(image) > 1.25:
				analysis = frappe.parse_json(version.analysis_json or "{}") or {}
				original_version = (analysis.get("subject_cutout") or {}).get("source_asset_version")
				original = next(
					(
						candidate
						for candidate in project.selected_media or []
						if candidate.asset_version == original_version
					),
					None,
				)
				if original and original.asset_version != row.asset_version:
					return ensure_transparent_reference(project, original)
				raise ValueError("Selected transparent reference retains studio fragments.")
			return row
	if not sam2_configured():
		raise ValueError("Exact-pixel reference compositing needs a configured cutout worker.")
	key = f"{row.reference_key}_cutout_{hashlib.sha256((row.asset_version + ':visual_v3').encode()).hexdigest()[:10]}"
	existing = next(
		(candidate for candidate in project.selected_media or [] if candidate.reference_key == key), None
	)
	if existing:
		return existing
	frappe.db.commit()  # Segmentation must not hold a project transaction open.
	content, evidence = cutout_studio_reference(path.read_bytes())
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{key}.png",
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "Media Project",
			"attached_to_name": project.name,
		}
	).insert(ignore_permissions=True)
	asset = create_media_asset(
		f"{row.label or row.reference_key} exact-pixel cutout",
		row.reference_role,
		file_url=file_doc.file_url,
		file_name=file_doc.name,
		source="Generated",
	)
	analysis = frappe.parse_json(version.analysis_json or "{}") or {}
	analysis["subject_cutout"] = {
		**evidence,
		"source_asset_version": row.asset_version,
		"source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
	}
	frappe.db.set_value(
		"Asset Version",
		asset["asset_version"],
		{
			"analysis_status": "Ready",
			"analysis_json": frappe.as_json(analysis),
		},
		update_modified=False,
	)
	project.reload()
	project.append(
		"selected_media",
		{
			"asset_version": asset["asset_version"],
			"reference_key": key,
			"identity_key": lineage_identity(project, row),
			"reference_role": row.reference_role,
			"label": f"{row.label or row.reference_key} (exact-pixel cutout)",
			"relative_size": row.relative_size,
			"keep_rule": row.keep_rule,
			"product_view": row.get("product_view"),
		},
	)
	project.save(ignore_permissions=True)
	return project.selected_media[-1]
