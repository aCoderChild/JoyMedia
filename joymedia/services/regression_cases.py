"""Regression cases for the keyframe stage, run against a real ComfyUI.

Each case builds a small project from generated assets (no client files), renders its keyframes on the server and
checks what can be checked mechanically: the picture has the project's shape, a pasted product or logo really sits
where the layout put it with its own colours, and nothing is pasted when the case has no cutouts. They guard the
general behaviour of the pipeline, so a change that fixes one project cannot silently break the others.

    bench --site <site> execute joymedia.services.regression_cases.run_all
"""

import io
import time

import frappe

SHAPES = {"Portrait": (720, 1280), "Landscape": (1280, 720)}


def _box_cutout(color=(200, 40, 40)):
	"""A cereal-box-like cutout with stripes, transparent around it."""
	from PIL import Image, ImageDraw

	image = Image.new("RGBA", (420, 560), (0, 0, 0, 0))
	draw = ImageDraw.Draw(image)
	draw.rounded_rectangle((30, 20, 390, 540), 18, fill=color + (255,))
	for y in range(80, 480, 60):
		draw.rectangle((60, y, 360, y + 24), fill=(250, 240, 220, 255))
	return image


def _logo_cutout():
	from PIL import Image, ImageDraw

	image = Image.new("RGBA", (600, 160), (0, 0, 0, 0))
	ImageDraw.Draw(image).ellipse((10, 10, 150, 150), fill=(30, 60, 200, 255))
	ImageDraw.Draw(image).rectangle((180, 50, 580, 110), fill=(30, 60, 200, 255))
	return image


def _png(image):
	output = io.BytesIO()
	image.save(output, "PNG")
	return output.getvalue()


def _add_reference(project, label, role, content, category):
	from joymedia.api.assets import select_project_asset
	from joymedia.services.media_asset_service import create_media_asset

	file_doc = frappe.get_doc({
		"doctype": "File", "file_name": f"{label}.png", "content": content, "is_private": 1,
	}).insert(ignore_permissions=True)
	asset = create_media_asset(label, category, file_url=file_doc.file_url, file_name=file_doc.name)
	select_project_asset(project.name, asset["media_asset"], role, label)


CASES = {
	"box-product-landscape": {
		"preset": "Landscape",
		"idea": "A cereal advertisement.",
		"references": [("Cereal box", "Product", "Product", _box_cutout), ("Brand logo", "Logo", "Brand", _logo_cutout)],
		"setting": "A sunny kitchen counter in the morning.",
		"video_prompt": "She opens the box and pours cereal. The camera slowly zooms in.",
		"expect": {"pasted": ["Cereal box", "Brand logo"], "keeps_box_noun": True},
	},
	"text-only-portrait": {
		"preset": "Portrait",
		"idea": "A calm ocean at sunrise.",
		"references": [],
		"setting": "A calm ocean at sunrise with soft clouds.",
		"video_prompt": "Waves roll slowly toward the shore.",
		"expect": {"pasted": [], "keeps_box_noun": False},
	},
}


def build_case(name):
	"""Create the case's project, references and one scene; returns the project name."""
	from joymedia.api.projects import create_project
	from joymedia.api.storyboard import approve_project_storyboard, set_project_shot_references

	case = CASES[name]
	frappe.set_user("Administrator")
	project = create_project(f"REGRESSION {name}", "", case["idea"])
	project.save_video_settings(total_duration_seconds=5, delivery_preset=case["preset"])
	for label, role, category, make in case["references"]:
		_add_reference(project, label, role, _png(make()), category)
	project.reload()
	shot = frappe.get_doc({
		"doctype": "Shot", "media_project": project.name, "shot_number": 1, "shot_name": name, "duration_seconds": 5,
		"image_prompt": case["setting"], "setting_prompt": case["setting"], "generation_prompt": case["video_prompt"],
		"handoff_type": "ending", "continuity_mode": "New Scene",
	}).insert(ignore_permissions=True)
	keys = [row.reference_key for row in project.selected_media]
	if keys:
		set_project_shot_references(project.name, shot.name, keys)
	approve_project_storyboard(project.name, True)
	frappe.db.commit()
	return project.name


def render_keyframe(project_name, timeout=900):
	"""Render the case's keyframe on the real server and return its image bytes."""
	from joymedia.services.keyframes import generate_keyframes, get_project_keyframes

	run = generate_keyframes(project_name)["run"]
	deadline = time.time() + timeout
	while time.time() < deadline:
		frappe.db.rollback()
		if frappe.db.get_value("Generation Run", run, "status") in ("Completed", "Failed", "Cancelled"):
			break
		time.sleep(10)
	row = get_project_keyframes(project_name)[0]
	if not row["url"]:
		return None
	return frappe.get_doc("File", {"file_url": row["url"]}).get_content()


def evaluate(name, image_bytes, project_name):
	"""Mechanical checks of a rendered keyframe; returns a list of (check, passed, detail)."""
	from PIL import Image

	from joymedia.services.subject_overlay import layout, pasted_references

	case, results = CASES[name], []
	if not image_bytes:
		return [("keyframe rendered", False, "no image")]
	image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
	want = SHAPES[case["preset"]]
	results.append(("shape", abs(image.width / image.height - want[0] / want[1]) < 0.02, f"{image.size} vs {want}"))
	project = frappe.get_doc("Media Project", project_name)
	shot = frappe.get_doc("Shot", frappe.get_all("Shot", filters={"media_project": project_name}, pluck="name")[0])
	pasted = pasted_references([{"reference_role": r.reference_role, "asset_version": r.asset_version} for r in shot.generation_inputs])
	labels = {row.asset_version: row.label for row in project.selected_media}
	results.append((
		"pasted references", sorted(labels[p["asset_version"]] for p in pasted) == sorted(case["expect"]["pasted"]),
		str(sorted(labels[p["asset_version"]] for p in pasted)),
	))
	if pasted:
		from PIL import Image as PILImage

		assets = [PILImage.open(p["path"]).convert("RGBA") for p in pasted]
		crops = [a.crop(a.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()) for a in assets]
		boxes = layout(image.size, [(p["role"], c.width, c.height, 1) for p, c in zip(pasted, crops)])
		for p, crop, (x, y, w, h) in zip(pasted, crops, boxes):
			region = image.crop((x + w // 4, y + h // 4, x + 3 * w // 4, y + 3 * h // 4))
			opaque = crop.resize((max(1, w), max(1, h))).crop((w // 4, h // 4, 3 * w // 4, 3 * h // 4))
			mean = lambda im: [sum(c) / max(1, len(c)) for c in zip(*[px[:3] for px in im.getdata() if len(px) < 4 or px[3] > 128])]
			distance = sum(abs(a - b) for a, b in zip(mean(region), mean(opaque)))
			results.append((f"{labels[p['asset_version']]} keeps its colours", distance < 90, f"colour distance {distance:.0f}"))
	return results


def run_case(name):
	project_name = build_case(name)
	image = render_keyframe(project_name)
	return {"case": name, "project": project_name, "checks": evaluate(name, image, project_name)}


def run_all():
	"""Run every case; raises nothing, returns each case's checks so a failure is visible."""
	report = [run_case(name) for name in CASES]
	for case in report:
		for check, passed, detail in case["checks"]:
			print(("PASS" if passed else "FAIL"), case["case"], "-", check, "-", detail)
	return report
