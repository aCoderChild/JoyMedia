"""Regression cases for the keyframe stage, run against a real ComfyUI.

Each case builds a small project from generated assets (no client files), renders its keyframes on the server and
checks what can be checked mechanically: the picture has the project's shape, a pasted product or logo really sits
where the layout put it with its own colours, and nothing is pasted when the case has no cutouts. They guard the
general behaviour of the pipeline, so a change that fixes one project cannot silently break the others.

    bench --site <site> execute joymedia.tests.support.regression_cases.run_all
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


def _generated_face():
	"""A presenter's face made by the keyframe workflow from text alone: a real face for the identity step to lock."""
	from PIL import Image

	from joymedia.services.workflows.comfyui import run_workflow_to_bytes
	from joymedia.services.workflows.resolver import build_execution_workflow

	name = frappe.db.get_value("Generation Workflow", {"workflow_key": "flux_pulid_keyframe"}, "name", order_by="version_number desc")
	workflow = build_execution_workflow(
		frappe.get_doc("Generation Workflow", name),
		inputs={"generation_prompt": "A studio portrait photograph of a friendly woman in her thirties with short dark hair, "
			"facing the camera, neutral grey background, soft light, sharp focus."},
		seed=4242, width=768, height=1024, fps=24, frame_count=1, output_prefix="joymedia/regression_face",
	)
	return Image.open(io.BytesIO(run_workflow_to_bytes(workflow, "50", timeout=900, forget=True))).convert("RGB")


def _png(image):
	output = io.BytesIO()
	image.save(output, "PNG")
	return output.getvalue()


def _add_reference(project, label, role, content, category):
	from joymedia.api.assets import select_project_asset
	from joymedia.services.intake.assets import create_media_asset

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
	"human-presenter-portrait": {
		"preset": "Portrait",
		"idea": "A presenter explains a product.",
		"references": [("Presenter", "Person", "Character", _generated_face)],
		"setting": "A modern office with a large window and plants.",
		"video_prompt": "The presenter stands by the window and gestures while talking to the camera.",
		"expect": {"pasted": [], "keeps_box_noun": False},
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
	from joymedia.services.keyframes.stage import generate_keyframes, get_project_keyframes

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

	from joymedia.services.keyframes.overlay import pasted_references

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

		for p in pasted:
			asset = PILImage.open(p["path"]).convert("RGBA")
			crop = asset.crop(asset.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox())
			# The asset's own dominant colour, and how many pixels of the frame are close to it: a pasted subject
			# shows up as a block of that colour, a missing or recoloured one does not.
			palette = crop.resize((24, 24)).getdata()
			colours = {}
			for r, g, b, a in palette:
				if a > 200:
					colours[(r // 32, g // 32, b // 32)] = colours.get((r // 32, g // 32, b // 32), 0) + 1
			dominant = max(colours, key=colours.get)
			close = sum(1 for r, g, b in image.getdata() if (r // 32, g // 32, b // 32) == dominant)
			share = close / (image.width * image.height)
			results.append((f"{labels[p['asset_version']]} appears in its own colours", share > 0.004, f"{share:.3%} of the frame"))
	# The movement text must keep a box the scene's own product is, and drop a zoom that would enlarge a pasted product.
	from joymedia.services.planning.prompts import compile_prompt_for_documents

	shot_doc = frappe.get_doc("Shot", shot.name)
	shot_doc.references = [{"reference_role": r.reference_role, "asset_version": r.asset_version} for r in shot_doc.generation_inputs]
	motion = compile_prompt_for_documents(shot_doc, frappe._dict(
		generation_mode="Multi-shot", global_instructions="", references=[{"asset_version": v, "label": l} for v, l in labels.items()]
	), prompt_source="motion")
	if case["expect"]["keeps_box_noun"]:
		results.append(("a box product keeps its box in the movement text", "opens the box" in motion, ""))
		results.append(("a zoom is removed when a product is pasted", "zooms in" not in motion, ""))
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
