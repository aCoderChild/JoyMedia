"""Describe reference images with a vision-language model before planning.

The planner model is text-only, so each selected image is described once by the
configured vision capability and the result is cached on its Asset Version
(`analysis_status`, `analysis_json`, `analysis_error`).
"""

import base64
import io
import json
from pathlib import Path

import frappe
import requests
from frappe import _

from joymedia.services.runtime.endpoints import endpoint
from joymedia.services.runtime.endpoints import is_configured as endpoint_is_configured
from joymedia.services.runtime.sampling import sampling

MAX_IMAGE_EDGE = 1024
VALID_KINDS = {"person", "place", "product", "other"}

ANALYSIS_PROMPT = """
Describe this reference image for a video director who cannot see it. Return only JSON:
{"kind": "person|place|product|other",
 "scene_type": "exterior|interior|amenity|landscape|portrait|product|other",
 "description": "at most 45 words of concrete visible details: layout, architecture, materials, furniture, colours, and what is seen through any windows",
 "identity_appearance": "for a physical character only: fixed colour, material, silhouette, visible ear count/shape/attachment, muzzle, eye design and limb proportions; exclude held props, pose and background; otherwise empty",
 "pose_and_support": "visible pose and support: standing, seated, lying, airborne or uncertain; name only the supporting surface actually visible",
 "outfit": "for a person: the exact garment type (name traditional dress such as a Vietnamese ao dai), colour, hair; otherwise empty",
 "lighting": "a few words"}
Rules: describe only what is visible, never guess. kind is "person" when a person is the main subject,
"place" for buildings, rooms and outdoor areas even if small people appear, and "product" for a single
object shown on its own: goods, packaging, jewellery, decor, and artworks, prints, plates or stickers
EVEN WHEN they depict a scene. For a product, describe the object first (shape, material, border,
colours), then what it depicts, e.g. "A round mosaic artwork with a jewelled border, depicting a harbour".
For a stylized character, describe body silhouette, head/body proportions, limb lengths and identifying
features before its incidental pose. Do not infer anatomy hidden by the pose.
""".strip()

PRODUCT_ANALYSIS_PROMPT = """
This image shows a PRODUCT that a video will feature as an object (held, displayed or used).
Describe it for a video director who cannot see it. Return only JSON:
{"kind": "product",
 "scene_type": "product",
 "description": "at most 45 words: first the object itself (type of object, shape, size impression, material, frame or border, finish, main colours), then what is printed, painted or shown on it, e.g. 'A tall frosted-glass bottle with a brushed silver cap; its label shows a green mountain logo'",
 "construction": {"rigidity": "flexible|rigid|uncertain", "evidence": "visible physical creases, seams, faces or edges supporting this observation; empty when uncertain"},
 "support_and_access": "visible way the product stands, hangs or is mounted, plus any visible dispensing opening; empty when not visible",
 "outfit": "",
 "lighting": "a few words"}
Rules: describe only what is visible, never guess. Never describe the depicted scene as if it were the setting.
Distinguish flexible wrapping from rigid construction using visible creases, seams and edges. A rectangular
silhouette alone does not establish a rigid box. Use pack/package when rigidity is uncertain; reserve
box/carton for visible rigid construction. Do not infer a hinged lid, an opening mechanism or hidden layers.
Describe visible hanging tabs, mounting holes, bases and dispensing openings precisely. Do not infer
that an item rests on a table when the image only shows its isolated package.
""".strip()

# Stored with each analysis; analyses made with an older prompt are redone.
ANALYSIS_VERSION = 6


def is_configured():
	return endpoint_is_configured("vision")


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
	# A generated character pose has a separate, versioned visual qualification.
	# Its stable pose/identity evidence remains usable when the generic caption
	# prompt changes; a vision outage must not invalidate an accepted view.
	if not as_product and analysis.get("description"):
		from joymedia.services.planning.pose_assets import _qualified_pose_metadata

		if _qualified_pose_metadata(analysis):
			return True
	return analysis.get("version") == ANALYSIS_VERSION and (
		not as_product or analysis.get("kind") == "product"
	)


def analyse_asset_version(asset_version_name, as_product=False):
	"""Analyse one image Asset Version and store the result. Failures are recorded, not raised."""
	file_url = frappe.db.get_value("Asset Version", asset_version_name, "file")
	# Generated Character views carry qualification provenance which is distinct
	# from a generic caption.  Re-running intake vision used to replace the
	# complete JSON document and silently erase that evidence, making an accepted
	# standing/side view look like an untrusted raw upload on the next batch.
	try:
		stored = json.loads(frappe.db.get_value("Asset Version", asset_version_name, "analysis_json") or "{}")
	except (TypeError, ValueError):
		stored = {}
	try:
		analysis = describe_image(
			_image_data_url(file_url), PRODUCT_ANALYSIS_PROMPT if as_product else ANALYSIS_PROMPT
		)
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
	for key in (
		"source_asset_version",
		"pose_qualification_version",
		"qualified_pose_and_support",
		"qualified_pose_view",
		"identity_appearance",
		"environment_contract",
		"product_view",
		"product_view_status",
		"visible_source_retained",
		"view_geometry_verified",
		"unknown_panels",
		"subject_cutout",
	):
		if stored.get(key) or stored.get(key) is False:
			analysis[key] = stored[key]
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
	configured = endpoint("vision")
	base_url = configured.base_url
	payload = {
		"model": configured.model,
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
		**sampling("intake_vision"),
	}
	timeout = configured.timeout
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
	analysis = {
		"kind": kind if kind in VALID_KINDS else "other",
		"scene_type": str(result.get("scene_type") or "").strip().lower()[:40],
		"description": str(result.get("description") or "").strip()[:400],
		"outfit": str(result.get("outfit") or "").strip()[:200],
		"lighting": str(result.get("lighting") or "").strip()[:100],
		"pose_and_support": str(result.get("pose_and_support") or "").strip()[:240],
		"identity_appearance": str(result.get("identity_appearance") or "").strip()[:500],
		"version": ANALYSIS_VERSION,
	}
	if as_product:
		construction = result.get("construction") or {}
		construction = construction if isinstance(construction, dict) else {}
		rigidity = construction.get("rigidity")
		evidence = construction.get("evidence")
		evidence = evidence.strip()[:240] if isinstance(evidence, str) else ""
		if not isinstance(rigidity, str) or rigidity not in {"flexible", "rigid"} or not evidence:
			rigidity, evidence = "uncertain", ""
		analysis["construction"] = {"rigidity": rigidity, "evidence": evidence}
		support_and_access = result.get("support_and_access")
		support_and_access = support_and_access.strip()[:240] if isinstance(support_and_access, str) else ""
		analysis["support_and_access"] = support_and_access
		if support_and_access:
			analysis["description"] = (
				f"Visible support and access: {support_and_access}. " + analysis["description"]
			)
		if evidence:
			analysis["description"] = (
				f"Visible construction: {rigidity}; {evidence}. " + analysis["description"]
			)
	return analysis


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
