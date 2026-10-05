"""Describe reference images with a vision-language model before planning.

The planner model is text-only, so each selected image is described once by the
model configured in `qwen_vl_base_url` / `qwen_vl_model` and the result is cached
on its Asset Version (`analysis_status`, `analysis_json`, `analysis_error`).
"""

import base64
import io
import json
from pathlib import Path

import frappe
import requests
from frappe import _


MAX_IMAGE_EDGE = 1024
DEFAULT_TIMEOUT = 120
VALID_KINDS = {"person", "place", "product", "other"}

ANALYSIS_PROMPT = """
Describe this reference image for a video director who cannot see it. Return only JSON:
{"kind": "person|place|product|other",
 "scene_type": "exterior|interior|amenity|landscape|portrait|product|other",
 "description": "at most 45 words of concrete visible details: layout, architecture, materials, furniture, colours, and what is seen through any windows",
 "outfit": "for a person: the exact garment type (name traditional dress such as a Vietnamese ao dai), colour, hair; otherwise empty",
 "lighting": "a few words"}
Rules: describe only what is visible, never guess. kind is "person" when a person is the main subject,
"place" for buildings, rooms and outdoor areas even if small people appear, and "product" for a single
object shown on its own: goods, packaging, jewellery, decor, and artworks, prints, plates or stickers
EVEN WHEN they depict a scene. For a product, describe the object first (shape, material, border,
colours), then what it depicts, e.g. "A round mosaic artwork with a jewelled border, depicting a harbour".
""".strip()

PRODUCT_ANALYSIS_PROMPT = """
This image shows a PRODUCT that a video will feature as an object (held, displayed or used).
Describe it for a video director who cannot see it. Return only JSON:
{"kind": "product",
 "scene_type": "product",
 "description": "at most 45 words: first the object itself (type of object, shape, size impression, material, frame or border, finish, main colours), then what is printed, painted or shown on it, e.g. 'A tall frosted-glass bottle with a brushed silver cap; its label shows a green mountain logo'",
 "outfit": "",
 "lighting": "a few words"}
Rules: describe only what is visible, never guess. Never describe the depicted scene as if it were the setting.
""".strip()

# Stored with each analysis; analyses made with an older prompt are redone.
ANALYSIS_VERSION = 2


def is_configured():
	return bool(frappe.conf.get("qwen_vl_base_url") and frappe.conf.get("qwen_vl_model"))


def ensure_project_image_analysis(project):
	"""Analyse every selected project image that has no Ready analysis yet."""
	if not is_configured():
		return []
	analysed = []
	for row in project.selected_media or []:
		if not row.asset_version:
			continue
		as_product = (row.reference_role or "") == "Product"
		version = frappe.db.get_value(
			"Asset Version",
			row.asset_version,
			["name", "media_asset", "file", "analysis_status", "analysis_json"],
			as_dict=True,
		)
		if not version or not version.file or _is_current(version, as_product):
			continue
		if frappe.db.get_value("Media Asset", version.media_asset, "media_type") != "Image":
			continue
		analyse_asset_version(version.name, as_product=as_product)
		analysed.append(version.name)
	return analysed


def _is_current(version, as_product=False):
	"""Whether the stored analysis was made with the current prompt for how the image is used."""
	if version.analysis_status != "Ready":
		return False
	try:
		analysis = json.loads(version.analysis_json or "{}")
	except ValueError:
		return False
	return analysis.get("version") == ANALYSIS_VERSION and (not as_product or analysis.get("kind") == "product")


def analyse_asset_version(asset_version_name, as_product=False):
	"""Analyse one image Asset Version and store the result. Failures are recorded, not raised."""
	file_url = frappe.db.get_value("Asset Version", asset_version_name, "file")
	try:
		analysis = describe_image(_image_data_url(file_url), PRODUCT_ANALYSIS_PROMPT if as_product else ANALYSIS_PROMPT)
	except Exception as exc:
		frappe.logger("joymedia.vision").warning(
			"Image analysis failed for Asset Version %s: %s", asset_version_name, exc
		)
		frappe.db.set_value(
			"Asset Version",
			asset_version_name,
			{"analysis_status": "Failed", "analysis_error": str(exc)[:500]},
			update_modified=False,
		)
		return None
	frappe.db.set_value(
		"Asset Version",
		asset_version_name,
		{
			"analysis_status": "Ready",
			"analysis_json": json.dumps(analysis, ensure_ascii=False, sort_keys=True),
			"analysis_error": None,
		},
		update_modified=False,
	)
	return analysis


def describe_image(data_url, prompt=ANALYSIS_PROMPT):
	base_url = frappe.conf.get("qwen_vl_base_url").rstrip("/")
	payload = {
		"model": frappe.conf.get("qwen_vl_model"),
		"messages": [
			{
				"role": "user",
				"content": [
					{"type": "image_url", "image_url": {"url": data_url}},
					{"type": "text", "text": prompt},
				],
			}
		],
		"response_format": {"type": "json_object"},
		"temperature": 0.1,
		"max_tokens": 400,
	}
	timeout = float(frappe.conf.get("qwen_vl_timeout") or DEFAULT_TIMEOUT)
	response = requests.post(f"{base_url}/chat/completions", json=payload, timeout=(10, timeout))
	response.raise_for_status()
	content = response.json()["choices"][0]["message"]["content"]
	return normalize_analysis(json.loads(content), as_product=prompt == PRODUCT_ANALYSIS_PROMPT)


def normalize_analysis(result, as_product=False):
	if not isinstance(result, dict):
		raise ValueError("Image analysis must be a JSON object.")
	kind = str(result.get("kind") or "").strip().lower()
	if as_product:
		kind = "product"
	return {
		"kind": kind if kind in VALID_KINDS else "other",
		"scene_type": str(result.get("scene_type") or "").strip().lower()[:40],
		"description": str(result.get("description") or "").strip()[:400],
		"outfit": str(result.get("outfit") or "").strip()[:200],
		"lighting": str(result.get("lighting") or "").strip()[:100],
		"version": ANALYSIS_VERSION,
	}


def _image_data_url(file_url):
	from PIL import Image

	if not file_url:
		frappe.throw(_("The reference image has no file."))
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	path = Path(file_doc.get_full_path())
	with Image.open(path) as image:
		image = image.convert("RGB")
		image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
		buffer = io.BytesIO()
		image.save(buffer, format="JPEG", quality=85)
	return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
