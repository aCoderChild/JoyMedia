frappe.ui.form.on("Asset Version", {
	refresh(frm) {
		set_media_metadata_visibility(frm);
	},

	media_asset(frm) {
		set_media_metadata_visibility(frm);
	},
});

async function set_media_metadata_visibility(frm) {
	if (!frm.doc.media_asset) {
		frm.toggle_display(["width", "height", "duration_seconds", "fps"], false);
		return;
	}

	const r = await frappe.db.get_value("Media Asset", frm.doc.media_asset, "media_type");
	const media_type = r.message?.media_type;
	const is_image = media_type === "Image";
	const is_video = media_type === "Video";
	const is_audio = media_type === "Audio";

	frm.toggle_display(["width", "height"], is_image || is_video);
	frm.toggle_display("duration_seconds", is_video || is_audio);
	frm.toggle_display("fps", is_video);
}
