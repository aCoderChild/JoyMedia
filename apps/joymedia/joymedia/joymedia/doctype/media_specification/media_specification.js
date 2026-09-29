// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Media Specification", {
	setup(frm) {
		frm.set_query("asset_version", "audio_cues", () => ({
			query:
				"joymedia.joymedia.doctype.audio_cue.audio_cue.get_audio_asset_versions",
		}));
	}
});
