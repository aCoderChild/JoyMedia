// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Quality Review", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.generation_artifact) {
			return;
		}

		frappe.db
			.get_value(
				"Generation Artifact",
				frm.doc.generation_artifact,
				"lifecycle_status"
			)
			.then(({ message }) => {
				if (!message || !["Temporary", "Retained"].includes(message.lifecycle_status)) {
					return;
				}

				frm.add_custom_button(
					__("Preview Artifact"),
					() => show_artifact_preview(frm),
					__("Review")
				);
			});
	},
});

function show_artifact_preview(frm) {
	const preview_url =
		"/api/method/joymedia.services.artifact_service.stream_review_artifact?quality_review_name=" +
		encodeURIComponent(frm.doc.name);
	const dialog = new frappe.ui.Dialog({
		title: __("Temporary Generation Preview"),
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "artifact_preview",
			},
		],
	});
	dialog.fields_dict.artifact_preview.$wrapper.html(
		`<video controls preload="metadata" style="max-width: 100%; width: 100%;">
			<source src="${preview_url}" type="video/mp4">
			${__("Your browser does not support video playback.")}
		</video>`
	);
	dialog.show();
}
