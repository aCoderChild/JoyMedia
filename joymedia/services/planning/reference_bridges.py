"""Durable H3 preparation clips and sampled-frame lineage, never final takes."""

import hashlib
import json
import subprocess
from fractions import Fraction
from pathlib import Path

import frappe


def store_bridge(project, source, identity, workflow, video, *, prompt, seed, purpose):
	checksum = hashlib.sha256(video).hexdigest()
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"reference-bridge-{purpose}-{checksum[:12]}.mp4",
			"content": video,
			"is_private": 1,
			"attached_to_doctype": "Media Project",
			"attached_to_name": project.name,
		}
	).insert(ignore_permissions=True)
	folder = Path(frappe.get_site_path("private", "joymedia-reference-bridges", project.name, checksum))
	folder.mkdir(parents=True, exist_ok=True)
	report = {
		"purpose": purpose,
		"project": project.name,
		"file": file.file_url,
		"clip_sha256": checksum,
		"source_asset_version": source.asset_version,
		"original": identity,
		"workflow": workflow.name,
		"workflow_hash": workflow.workflow_hash,
		"seed": seed,
		"prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
		"samples": [],
		"status": "preparation_candidate_not_final_video",
	}
	(folder / "manifest.json").write_text(json.dumps(report, indent=2))
	frappe.db.commit()
	return {"path": file.get_full_path(), "folder": folder, "report": report}


def sample_bridge(bridge):
	probe = json.loads(
		subprocess.check_output(
			[
				"ffprobe",
				"-v",
				"error",
				"-select_streams",
				"v:0",
				"-show_entries",
				"format=duration:stream=nb_frames,avg_frame_rate",
				"-of",
				"json",
				bridge["path"],
			]
		)
	)
	duration = float(probe["format"]["duration"])
	if not 0 < duration <= 20:
		raise ValueError("Preparation bridge has an invalid duration.")
	stream = probe["streams"][0]
	fps = float(Fraction(stream["avg_frame_rate"]))
	count = int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else round(duration * fps)
	if fps <= 0 or count < 2:
		raise ValueError("Preparation bridge has no usable motion frames.")
	for fraction in (0.95, 0.82, 0.69, 0.56, 0.43, 0.30):
		index = round((count - 1) * fraction)
		second = index / fps
		path = bridge["folder"] / f"frame-{second:.3f}.png"
		result = subprocess.run(
			[
				"ffmpeg",
				"-v",
				"error",
				"-y",
				"-i",
				bridge["path"],
				"-vf",
				f"select=eq(n\\,{index})",
				"-vsync",
				"0",
				"-frames:v",
				"1",
				str(path),
			],
			capture_output=True,
			timeout=60,
		)
		if result.returncode or not path.exists():
			continue
		yield path.read_bytes(), second


def record_sample(bridge, content, second, qualified):
	checksum = hashlib.sha256(content).hexdigest()
	report = bridge["report"]
	row = {"timestamp": second, "frame_sha256": checksum, "reference_qualified": bool(qualified)}
	report["samples"].append(row)
	(bridge["folder"] / "manifest.json").write_text(json.dumps(report, indent=2))
	if qualified:
		folder = Path(frappe.get_site_path("private", "joymedia-reference-frame-lineage", report["project"]))
		folder.mkdir(parents=True, exist_ok=True)
		(folder / f"{checksum}.json").write_text(
			json.dumps(
				{
					"file": report["file"],
					"clip_sha256": report["clip_sha256"],
					"workflow": report["workflow"],
					"workflow_hash": report["workflow_hash"],
					**row,
				}
			)
		)


def frame_provenance(project, content):
	checksum = hashlib.sha256(content).hexdigest()
	path = Path(
		frappe.get_site_path("private", "joymedia-reference-frame-lineage", project.name, checksum + ".json")
	)
	return json.loads(path.read_text()) if path.exists() else None


def product_view_from_h3(project, source, view, accepts):
	from PIL import Image

	from joymedia.services.project.reference_lineage import original_reference
	from joymedia.services.workflows.comfyui import run_workflow_to_bytes, upload_frappe_file
	from joymedia.services.workflows.resolver import build_execution_workflow
	from joymedia.workflow_adapters import get_workflow_adapter

	name = frappe.conf.get("joymedia_product_view_video_workflow") or frappe.conf.get(
		"joymedia_pose_video_workflow"
	)
	if not name:
		rows = frappe.get_all(
			"Generation Workflow",
			filters={"workflow_key": "minimax_h3_i2v"},
			pluck="name",
			order_by="creation desc",
			limit=1,
		)
		name = rows[0] if rows else None
	if not name:
		raise ValueError("No H3 product-view preparation workflow is registered.")
	workflow = frappe.get_doc("Generation Workflow", name)
	identity = original_reference(source.asset_version)
	file = frappe.get_doc("File", {"file_url": identity["file"]})
	with Image.open(file.get_full_path()) as image:
		factor = 640 / max(image.size)
		width, height = [max(320, round(n * factor / 32) * 32) for n in image.size]
	upload = upload_frappe_file(identity["file"])["server_path"]
	angle = view.replace("_", " ")
	prompt = (
		"For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
		"integrated_multimodal_description: [Shot 1] Exactly one stationary original product on a neutral studio surface. "
		f"The camera smoothly moves from the supplied viewpoint to a clear {angle} product view, then holds. "
		"Preserve the original shape, dimensions, material, construction, colour, logo, illustration and every shared readable printed line. "
		"Do not open, deform, redesign or turn soft wrapping into a rigid carton. No new printing, physical mascot, person, hand or extra product. "
		"Package illustrations remain flat artwork. Keep the complete product and its contact shadow in frame. "
		"Hidden panels remain inferred; do not invent claims, barcodes or detailed text.\n\noverall_soundscape: N/A\n\nnon_diegetic_music: N/A"
	)
	output = get_workflow_adapter(workflow).extract_execution_metadata(
		frappe.parse_json(workflow.workflow_json)
	)["primary_output_node_key"]
	for attempt in range(2):
		seed = int(
			hashlib.sha256(f"{identity['content_hash']}:{view}:{attempt}".encode()).hexdigest()[:12], 16
		)
		frappe.db.commit()
		graph = build_execution_workflow(
			workflow,
			inputs={"first_frame": [upload], "generation_prompt": prompt},
			seed=seed,
			width=width,
			height=height,
			fps=float(workflow.output_fps or 24),
			frame_count=73,
			output_prefix=f"joymedia/product-view-bridge/{seed}",
		)
		video = run_workflow_to_bytes(graph, output, forget=True)
		bridge = store_bridge(
			project, source, identity, workflow, video, prompt=prompt, seed=seed, purpose="product"
		)
		for content, second in sample_bridge(bridge):
			qualified = accepts(content)
			record_sample(bridge, content, second, qualified)
			if qualified:
				return content
	raise ValueError("H3 product angle did not retain the verified source traits and geometry.")
