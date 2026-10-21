"""Speech provider boundary: configured audio graph, or the legacy Edge adapter."""

import asyncio
import hashlib
import re

import frappe


def provider(voice=None):
	from joymedia.services.workflows.capabilities import configured_workflow, require_controls

	workflow = configured_workflow("narration")
	if workflow:
		version = frappe.get_doc("Generation Workflow", workflow)
		if version.output_media_type != "Audio":
			raise ValueError("Narration workflow must produce audio.")
		require_controls(version, {"speech"})
		if voice and not any(row.binding_key == "voice" for row in version.bindings):
			raise ValueError("The configured speech workflow does not expose a voice control.")
		return {"workflow": workflow, "voice": str(voice or ""), "key": workflow}
	voice = str(voice or frappe.conf.get("joymedia_tts_voice") or "vi-VN-HoaiMyNeural")
	if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}-[A-Za-z0-9]+Neural", voice):
		raise ValueError("Choose a supported voice for the configured Edge speech adapter.")
	return {
		"workflow": None,
		"voice": voice,
		"key": "edge",
		"proxy": frappe.conf.get("joymedia_tts_proxy") or None,
	}


def synthesize(text, configuration, output, seconds):
	if configuration["workflow"]:
		from joymedia.services.workflows.comfyui import run_workflow_to_bytes
		from joymedia.services.workflows.resolver import build_execution_workflow
		from joymedia.workflow_adapters import get_workflow_adapter

		version = frappe.get_doc("Generation Workflow", configuration["workflow"])
		fps = float(version.output_fps or 24)
		inputs = {"generation_prompt": text}
		if configuration["voice"]:
			inputs["voice"] = configuration["voice"]
		graph = build_execution_workflow(
			version,
			inputs=inputs,
			seed=int(hashlib.sha256(text.encode()).hexdigest()[:12], 16),
			width=1,
			height=1,
			fps=fps,
			frame_count=max(1, round(seconds * fps)),
			output_prefix=f"joymedia/speech/{frappe.generate_hash(length=12)}",
		)
		node = get_workflow_adapter(version).extract_execution_metadata(graph)["primary_output_node_key"]
		output.write_bytes(run_workflow_to_bytes(graph, node, timeout=900, forget=True))
		return
	try:
		import edge_tts
	except ImportError as exc:
		raise ValueError("Install the narration extra or configure a speech workflow.") from exc

	async def run():
		await asyncio.wait_for(
			edge_tts.Communicate(text, configuration["voice"], proxy=configuration.get("proxy")).save(
				str(output)
			),
			timeout=90,
		)

	asyncio.run(run())
