"""Offline paired identity-judge qualification; never a production approver."""

import base64
import hashlib
import io
import json
import subprocess

import frappe
import requests
from PIL import Image, ImageOps

from joymedia.services.runtime.endpoints import endpoint, structured_response

SCHEMA = {
	"type": "object",
	"properties": {
		"verdict": {"type": "string", "enum": ["consistent", "drift", "uncertain"]},
		"reason": {"type": "string"},
	},
	"required": ["verdict", "reason"],
	"additionalProperties": False,
}


def _image(data):
	with Image.open(io.BytesIO(data)) as source:
		source = ImageOps.exif_transpose(source).convert("RGBA")
		canvas = Image.new("RGBA", source.size, "white")
		canvas.alpha_composite(source)
		canvas.thumbnail((768, 768))
		buffer = io.BytesIO()
		canvas.convert("RGB").save(buffer, "PNG")
	return {
		"type": "image_url",
		"image_url": {"url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()},
	}


def verify(references, candidates, frozen, *, run_name=None):
	actors = list(
		dict.fromkeys(
			r["asset_version"]
			for r in references or []
			if str(r.get("reference_role") or "").lower() in {"character", "person"}
			and r.get("asset_version")
		)
	)
	if not actors or not frozen.get("screen_identity"):
		return None
	if len(actors) > 4 or not 1 <= len(candidates) <= 6:
		raise ValueError("Identity screening exceeds the reference/image budget.")
	configured = endpoint("vision")
	if configured.model != frozen.get("identity_model"):
		raise ValueError("Identity screening service differs from the frozen model.")
	messages = [
		{
			"type": "text",
			"text": f"First {len(actors)} images are immutable character/person identity references, possibly multiple views of the same subject. The following images are candidate frames. Compare the actual visual subjects. Check eye type (solid beads versus eyeballs with white sclera), nose/mouth design, markings, accessories, colours, body proportions, surface finish and attached limb type. Pose and normal blinking may change. Human hands replacing mascot paws, new costume/features, changed facial design, extra subjects or changed printed decoration are drift. Packaging identity is checked separately: do not judge camera framing or package size here. Use consistent only when identity is visibly supported across every candidate; use uncertain for hidden or unclear evidence. Give the observed reason. Return the structured verdict.",
		}
	]
	from PIL import ImageDraw

	panels = []
	for version in actors:
		file = frappe.db.get_value("Asset Version", version, "file")
		panels.append(("SOURCE " + version, frappe.get_doc("File", {"file_url": file}).get_content()))
	panels.extend(("CANDIDATE " + str(index + 1), data) for index, data in enumerate(candidates))
	columns = min(4, len(panels))
	sheet = Image.new("RGB", (columns * 384, ((len(panels) + columns - 1) // columns) * 664), "#eeeeee")
	draw = ImageDraw.Draw(sheet)
	for index, (label, data) in enumerate(panels):
		with Image.open(io.BytesIO(data)) as image:
			image = ImageOps.exif_transpose(image).convert("RGBA")
			tile = Image.new("RGBA", image.size, "white")
			tile.alpha_composite(image)
			tile.thumbnail((376, 632))
			x = (index % columns) * 384
			y = (index // columns) * 664
			sheet.paste(tile.convert("RGB"), (x + (384 - tile.width) // 2, y + 28 + (632 - tile.height) // 2))
			draw.text((x + 5, y + 5), label, fill="black")
	buffer = io.BytesIO()
	sheet.save(buffer, "PNG")
	messages[0]["text"] += (
		" The single evidence image is a labelled contact sheet: SOURCE panels are references; CANDIDATE panels are frames. Compare those panels."
	)
	messages.append(_image(buffer.getvalue()))
	response = requests.post(
		configured.base_url + "/chat/completions",
		json={
			"model": configured.model,
			"messages": [{"role": "user", "content": messages}],
			"temperature": 0,
			"max_tokens": 300,
			**structured_response(configured, SCHEMA, "reference_identity"),
		},
		timeout=(10, configured.timeout),
	)
	if not response.ok:
		raise ValueError("Identity screening service rejected the evidence request: " + response.text[:300])
	text = response.json()["choices"][0]["message"]["content"]
	try:
		report = json.loads(text)
	except (ValueError, TypeError):
		raise ValueError("Identity screening returned no usable evidence.")
	if report.get("verdict") not in {"consistent", "drift", "uncertain"} or not isinstance(
		report.get("reason"), str
	):
		raise ValueError("Identity screening returned invalid evidence.")
	report.update(
		model=configured.model,
		sources=actors,
		candidate_sha256=[hashlib.sha256(data).hexdigest() for data in candidates],
		acceptance="screening_only_not_release_approval",
	)
	if run_name:
		frappe.get_doc(
			dict(
				doctype="File",
				file_name="identity-screening.json",
				content=json.dumps(report).encode(),
				is_private=1,
				attached_to_doctype="Generation Run",
				attached_to_name=run_name,
			)
		).insert(ignore_permissions=True)
	if report["verdict"] != "consistent":
		raise ValueError("Identity verification: " + report["verdict"] + " — " + report["reason"][:600])
	return report


if __name__ == "__main__":
	import argparse
	from pathlib import Path

	from joymedia.services.review.consistency import sample_frames

	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("site")
	parser.add_argument("spec", type=Path)
	parser.add_argument("output", type=Path)
	parser.add_argument("--vision-base-url")
	args = parser.parse_args()
	frappe.init(site=args.site, sites_path="sites")
	frappe.connect()
	if args.vision_base_url:
		frappe.conf.joymedia_vision = {
			**dict(frappe.conf.joymedia_vision or {}),
			"base_url": args.vision_base_url,
		}
	results = []
	for case in json.loads(args.spec.read_text()):
		version = frappe.get_doc("Asset Version", case["candidate_asset_version"])
		file = frappe.get_doc("File", {"file_url": version.file})
		try:
			report = verify(
				case["references"],
				sample_frames(file.get_full_path(), 4),
				{"screen_identity": True, "identity_model": endpoint("vision").model},
			)
			observed = report["verdict"]
		except ValueError as exc:
			report = {"error": str(exc)}
			observed = (
				"drift"
				if str(exc).startswith("Identity verification: drift")
				else "uncertain"
				if str(exc).startswith("Identity verification: uncertain")
				else "error"
			)
		results.append(
			{
				"name": case["name"],
				"expected": case["expected"],
				"observed": observed,
				"passed": observed == case["expected"],
				"report": report,
			}
		)
		print(case["name"], observed, flush=True)
	args.output.write_text(
		json.dumps({"qualified": all(row["passed"] for row in results), "results": results}, indent=2)
	)
	frappe.destroy()
	raise SystemExit(0 if all(row["passed"] for row in results) else 1)
