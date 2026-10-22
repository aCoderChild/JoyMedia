"""Speech provider boundary: configured audio graph, or the legacy Edge adapter."""

import asyncio
import hashlib
import re

import frappe

# Default Edge voice per spoken language when no voice is chosen or configured.
LANGUAGE_VOICES = {"vi": "vi-VN-HoaiMyNeural", "en": "en-US-AriaNeural"}


def spoken_language(text):
	"""'vi' for Vietnamese text, otherwise 'en'; only used to pick a default voice."""
	from joymedia.services.planning.creative import VIETNAMESE

	return "vi" if VIETNAMESE.search(str(text or "")) else "en"


def provider(voice=None, text=None):
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
	voice = str(
		voice
		or frappe.conf.get("joymedia_tts_voice")
		or LANGUAGE_VOICES[spoken_language(text) if text is not None else "vi"]
	)
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

	async def run(proxy):
		await asyncio.wait_for(
			edge_tts.Communicate(text, configuration["voice"], proxy=proxy).save(str(output)),
			timeout=90,
		)

	try:
		asyncio.run(run(configuration.get("proxy")))
	except OSError as exc:
		# An unreachable or hanging proxy (e.g. its SSH forward is down) must not
		# stop narration; the direct route is tried once. A proxy that answers
		# without audio raises a non-OSError and still fails as before.
		if not configuration.get("proxy"):
			raise
		frappe.logger("joymedia.audio").warning("Narration proxy unreachable (%s); trying the direct route.", exc)
		asyncio.run(run(None))
