frappe.ui.form.on("Generation Artifact", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.media_type !== "Video" || !frm.doc.frappe_file) {
			return;
		}

		frm.add_custom_button(__("View Video"), () => {
			show_video_preview(frm.doc.frappe_file);
		});

		frm.add_custom_button(__("Open Video File"), () => {
			window.open(frm.doc.frappe_file, "_blank", "noopener");
		});
	},
});

function show_video_preview(file_url) {
	const dialog = new frappe.ui.Dialog({
		title: __("Generated Video"),
		fields: [{ fieldtype: "HTML", fieldname: "video_preview" }],
		primary_action_label: __("Close"),
		primary_action() {
			dialog.hide();
		},
	});

	dialog.fields_dict.video_preview.$wrapper.html(`
		<video controls autoplay style="width: 100%; max-height: 70vh;">
			<source src="${frappe.utils.escape_html(file_url)}" type="video/mp4">
			${__("Your browser does not support video playback.")}
		</video>
	`);
	dialog.show();
}
