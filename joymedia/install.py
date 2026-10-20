"""One command that makes a site able to render: `bench --site <site> execute joymedia.install.setup`.

It registers the keyframe, video and sound-effect workflows and the pipeline that chains them (each is an
immutable version, created only when it differs from what the site already has), and reports what is still
missing. Promotion (making a pipeline the one production uses) is deliberate, so it only happens with
`promote=1`: `bench --site <site> execute joymedia.install.setup --kwargs '{"promote": 1}'`.
"""

import frappe


def setup(promote=0):
	from joymedia.patches import (
		register_flux2_klein_pipeline,
		register_flux_pulid_h3_pipeline,
		register_mmaudio_sfx_workflow,
	)

	report = {}
	# Klein supports each mascot/product/place as a separate reference. PuLID's
	# human-face branch is inappropriate for a mascot-led workbook.
	report["pipeline"] = register_flux2_klein_pipeline.execute()
	report["video_workflow"] = register_flux_pulid_h3_pipeline._current_version(
		register_flux_pulid_h3_pipeline.H3_WORKFLOW_KEY
	)
	report["keyframe_workflow"] = frappe.db.get_value(
		"Generation Workflow",
		{"workflow_key": register_flux2_klein_pipeline.WORKFLOW_KEY},
		"name",
		order_by="version_number desc",
	)
	report["sound_workflow"] = register_mmaudio_sfx_workflow.execute()
	from joymedia.patches import register_mmaudio_bgm_workflow

	report["music_workflow"] = register_mmaudio_bgm_workflow.execute()
	report["pipeline"] = (
		register_flux_pulid_h3_pipeline._pipeline_with(report["keyframe_workflow"], report["video_workflow"])
		if report["keyframe_workflow"] and report["video_workflow"]
		else None
	)
	active = frappe.conf.get("joymedia_active_generation_pipeline") or frappe.defaults.get_global_default(
		"joymedia_active_generation_pipeline"
	)
	if str(promote).lower() in {"1", "true", "yes"} and report["pipeline"] and active != report["pipeline"]:
		from frappe.installer import update_site_config

		update_site_config("joymedia_active_generation_pipeline", report["pipeline"])
		active = report["pipeline"]
	report["active_pipeline"] = active
	report["todo"] = [
		message
		for ok, message in (
			(
				report["video_workflow"],
				"The video workflow could not be registered (is the H3 graph valid?).",
			),
			(report["pipeline"], "No pipeline chains the keyframe and video workflows."),
			(active, "No pipeline is promoted: run again with promote=1 after a smoke test."),
			(
				active == report["pipeline"],
				"The promoted pipeline is not the newest registered one; promote=1 switches it.",
			),
			(frappe.conf.get("comfyui_base_url"), "Set comfyui_base_url in site_config.json."),
		)
		if not ok
	]
	frappe.db.commit()
	return report
