import json

import frappe
import requests
from frappe import _


DEFAULT_TIMEOUT = 120


def generate_video_plan(
	*,
	product_name: str,
	target_audience: str,
	video_idea: str,
	total_video_duration: float,
	target_fps: float,
	scene_count: int,
	reference_template: dict | None = None,
	reference_images: list[dict] | None = None,
) -> dict:
	base_url = frappe.conf.get("qwen_base_url")
	model = frappe.conf.get("qwen_model")
	if not base_url:
		frappe.throw(_("qwen_base_url is not configured."))
	if not model:
		frappe.throw(_("qwen_model is not configured."))

	if reference_template:
		instruction = (
			"Create a new MiniMax H3 commercial plan based on the supplied reference template.\n\n"
			"Preserve its cinematography, pacing, composition, motion style and lighting style.\n\n"
			"Adapt the subject and product-specific content to the new product."
		)
	else:
		instruction = f"""
Bạn là Đạo diễn TVC Điện ảnh Quốc tế chuyên nghiệp cho MiniMax H3 / Wan 2.2.

Hãy phân tích:
- Product / Project
- Target Audience
- Video Idea nếu được cung cấp
- toàn bộ hình ảnh tham chiếu

Sau đó tạo chính xác {scene_count} cảnh TVC.

Mỗi cảnh phải là một Prompt 5 lớp hoàn chỉnh và chi tiết:

[Camera]
Mô tả shot size, lens/focal length, camera angle, perspective,
composition, camera movement, direction và speed.

[Subject]
Mô tả chính xác chủ thể nhìn thấy trong ảnh tham chiếu:
appearance, material, spatial position, foreground/background
và các visual details quan trọng.

[Motion]
Mô tả subject motion, camera-relative motion và environmental motion.
Chuyển động phải mượt, tự nhiên, có direction, speed và progression rõ ràng.

[Lighting & Environment]
Mô tả light source, direction, intensity, color temperature,
contrast, reflections, shadows, atmosphere và depth.

[Audio SFX]
Mô tả synchronized sound effects, ambience và music.
Sử dụng timestamps khi phù hợp.

Không trả về các mô tả ngắn như:
"wide", "pan left", "static", "natural daylight".

Mỗi field phải đủ chi tiết để có thể sử dụng trực tiếp
trong prompt cho MiniMax H3 / Wan 2.2.
""".strip()

	response_shape = (
		'{"shots":[{"shot_number":1,"reference_image_index":1,"camera":"...",'
		'"subject":"...","motion":"...","lighting":"...","audio":"..."}]}'
		if reference_images
		else '{"shots":[{"shot_number":1,"camera":"...","subject":"...",'
		'"motion":"...","lighting":"...","audio":"..."}]}'
	)

	user_prompt = (
		f"{instruction}\n\n"
		f"PRODUCT NAME\n{product_name}\n\n"
		f"TARGET AUDIENCE\n{target_audience}\n\n"
		f"VIDEO IDEA\n{video_idea or ''}\n\n"
		f"TOTAL VIDEO DURATION: {total_video_duration} seconds\n"
		f"TARGET FPS: {target_fps}\n"
		f"NUMBER OF SCENES: {scene_count}\n\n"
		f"Return exactly {scene_count} shots.\n\n"
		"Return only valid JSON with this shape:\n"
		f"{response_shape}"
	)
	if reference_template:
		user_prompt += "\n\nREFERENCE TEMPLATE\n" + json.dumps(reference_template, ensure_ascii=False)
	if reference_images:
		user_prompt += (
			"\n\nPROJECT IMAGES\n"
			f"You are given {len(reference_images)} numbered project images.\n"
			"For every shot, choose the ONE project image that visually grounds that shot and "
			"return its number as reference_image_index.\n"
			"reference_image_index must be an integer between 1 and "
			f"{len(reference_images)}.\n"
			"Do not invent rooms, objects, architecture, or product details that are not visible "
			"in the selected reference image."
		)

	user_content = [{"type": "text", "text": user_prompt}]
	for image in reference_images or []:
		user_content.append(
			{
				"type": "text",
				"text": f"REFERENCE IMAGE {image['index']}: {image['asset_name']}",
			}
		)
		user_content.append(
			{"type": "image_url", "image_url": {"url": image["data_url"]}}
		)

	try:
		response = requests.post(
			f"{base_url.rstrip('/')}/chat/completions",
			json={
				"model": model,
				"messages": [
					{
						"role": "system",
						"content": "You produce structured JSON video plans. Do not include markdown fences or commentary.",
					},
					{"role": "user", "content": user_content},
				],
				"response_format": {"type": "json_object"},
			},
			timeout=DEFAULT_TIMEOUT,
		)
	except requests.ConnectionError as exc:
		frappe.throw(_("Unable to connect to Qwen: {0}").format(str(exc)))

	if not response.ok:
		frappe.throw(
			_("Qwen request failed ({0}): {1}").format(response.status_code, response.text)
		)

	try:
		content = response.json()["choices"][0]["message"]["content"]
		result = json.loads(content)
	except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
		frappe.throw(_("Qwen returned invalid video plan JSON: {0}").format(str(exc)))

	_validate_video_plan(
		result,
		reference_image_count=len(reference_images or []),
		scene_count=scene_count,
	)
	return result


def _validate_video_plan(result, reference_image_count=0, scene_count=None):
	if not isinstance(result, dict) or not isinstance(result.get("shots"), list):
		frappe.throw(_("Qwen video plan must contain a shots list."))

	if not result["shots"]:
		frappe.throw(_("Qwen video plan must contain at least one shot."))

	if scene_count is not None and len(result["shots"]) != scene_count:
		frappe.throw(_("Qwen returned {0} shots; expected {1}.").format(len(result["shots"]), scene_count))

	required_fields = {"shot_number", "camera", "subject", "motion", "lighting", "audio"}
	if reference_image_count:
		required_fields.add("reference_image_index")

	normalized_shots = []

	for shot in result["shots"]:
		if not isinstance(shot, dict) or not required_fields.issubset(shot):
			frappe.throw(_("Each Qwen shot must contain the required video plan fields."))

		if type(shot["shot_number"]) is not int or shot["shot_number"] < 1:
			frappe.throw(_("Shot number must be a positive integer."))

		normalized = {
			"shot_number": shot["shot_number"],
			"camera": str(shot["camera"]).strip(),
			"subject": str(shot["subject"]).strip(),
			"motion": str(shot["motion"]).strip(),
			"lighting": str(shot["lighting"]).strip(),
			"audio": str(shot["audio"]).strip(),
		}

		if reference_image_count:
			index = shot["reference_image_index"]
			if type(index) is not int or index < 1 or index > reference_image_count:
				frappe.throw(_("Invalid reference image index."))
			normalized["reference_image_index"] = index

		normalized_shots.append(normalized)

	result["shots"] = normalized_shots
