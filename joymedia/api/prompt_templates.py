"""Reusable, product-neutral story and scene prompts for the Studio library."""

import frappe

TEMPLATES = (
	{
		"id": "shera_video_33",
		"title": "Shera · Video 33 — Nhân vật sử dụng sản phẩm",
		"title_en": "Shera · Video 33 — Character product story",
		"description": "Nhân vật sử dụng sản phẩm trong không gian ấm áp.",
		"description_en": "A character uses the product in a warm setting.",
		"idea": "Adapt the eight-beat structure of Shera video 33 to the supplied product and character. Target 30 seconds: (1) 3s wide: the character places the product on a supported surface and releases it; (2) 4s close: steady the product and extract one usable item; (3) 4s medium close: open or prepare that item; (4) 4s close: show one gentle use; (5) 3s medium: dispose of or put away the used item; (6) 4s full: carry the same product a short reachable distance; (7) 4s close: place it securely and reveal its front; (8) 4s medium close: a friendly gesture beside the product. Adapt actions to the actual product and available references. Establish contact before release, keep limbs and identity consistent, and use only verified visible packaging. Use natural synchronized effects, no unsupported claims.",
		"scene": "Follow this scene's action and continuity from the character product story: keep the same character and product, show support and hand contact before release, preserve proportions and visible packaging, and use a camera angle supported by the references.",
		"source_project": "PRJ-02586",
		"source_label": "Shera video 33",
		"duration_seconds": 30,
	},
	{
		"id": "auntie_video_5",
		"title": "AUNTIE · Video 5 — Thời trang và chi tiết",
		"title_en": "AUNTIE · Video 5 — Fashion and details",
		"description": "Người mẫu, mở gói và cận cảnh chất liệu.",
		"description_en": "Model, unpacking and fabric details.",
		"idea": "Adapt the eight-beat structure of AUNTIE video 5 to the supplied apparel and model references. Target 30 seconds: (1) 4s wide: model walks toward camera, garment front visible; (2) 3s medium: naturally turn to show the back only if a verified back reference exists; otherwise use another supported view; (3) 3s close: demonstrator opens an already-unsealed soft bag while securing the garment; (4) 4s: remove the same garment, place it on a surface and release only after support; (5) 4s: gently pat and smooth supported fabric without stretching the print; (6) 3s close: pinch and release a small fabric fold; (7) 4s: smooth and reveal the unobstructed front design; (8) 5s: return to the same model wearing the garment in the original setting. Keep identity, garment shape, print, lighting and contact continuous. Use synchronized footsteps and fabric sounds; avoid invented packaging or material claims.",
		"scene": "Follow this scene's action and continuity from the fashion story: use the same referenced garment and actor, preserve print and fabric shape, show contact and support, and reveal only verified sides.",
		"source_project": "PRJ-02563",
		"source_label": "AUNTIE video 5",
		"duration_seconds": 30,
	},
	{
		"id": "shera_video_14",
		"title": "Shera · Video 14 — Khoảnh khắc dịu dàng",
		"title_en": "Shera · Video 14 — A gentle moment",
		"description": "Sự cố nhỏ dẫn đến trải nghiệm sản phẩm ấm áp.",
		"description_en": "A small mishap leads to a warm product moment.",
		"idea": "Adapt the seven-beat structure of Shera video 14 to the supplied product and character, over 30 seconds: (1) 4s wide: establish a cheerful everyday moment with the product visible; (2) 3s medium: a small accidental spill follows clear contact with a cup; (3) 4s close: extract one item and blot the spill; (4) 5s macro: show a product detail supported by the references; (5) 5s close: use a fresh item for gentle personal care; (6) 4s medium close: show the character's warm reaction beside the product; (7) 5s hero shot: finish with the product and character clearly visible. Keep the same room, screen direction, character and packaging consistent. Show contact before movement, keep used and fresh items separate, and add verified text in post-production. Do not invent product claims or unsupported construction details.",
		"scene": "Keep the character, product and setting consistent with this scene. Show clear contact and support, preserve the packaging and character proportions, and use a fresh item for personal care.",
		"source_project": "PRJ-02558",
		"source_label": "Shera video 14",
		"duration_seconds": 30,
	},
)


def _source_video(project_name):
	"""The finished video a template was derived from, when the reader may open it.

	A template describes a structure, so being able to watch the original is the
	only way to judge whether a reproduction matches. Readers without access to
	the source project simply get no preview rather than an error.
	"""
	if not project_name or not frappe.db.exists("Media Project", project_name):
		return None
	try:
		project = frappe.get_doc("Media Project", project_name)
		project._require_read_access()
	except Exception:
		return None
	version = project.current_output_asset_version
	if not version:
		return None
	return frappe.db.get_value("Asset Version", version, "file") or None


@frappe.whitelist()
def list_prompt_templates():
	"""The same curated library is available to all authenticated Studio users."""
	if frappe.session.user == "Guest":
		frappe.throw("Authentication required", frappe.PermissionError)
	return [
		dict(template, source_video=_source_video(template.get("source_project"))) for template in TEMPLATES
	]
