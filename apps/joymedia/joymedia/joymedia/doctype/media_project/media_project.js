frappe.ui.form.on("Media Project", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Open Studio"), () => {
			window.location.href = `/joymedia/projects/${encodeURIComponent(frm.doc.name)}`;
		});

		frm.add_custom_button(__("Video Settings"), () => {
			show_video_settings_dialog(frm);
		});

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Generate Video"), () => {
				generate_project_video(frm);
			});
		}

		if (frm.doc.status === "Needs Attention") {
			frm.add_custom_button(__("Retry Failed Generation"), () => {
				retry_failed_generation(frm);
			});
		}
	},
});

function show_video_settings_dialog(frm, after_save) {
	frm.call("get_video_settings", {}, (r) => {
		if (r.exc) return;

		const settings = r.message || {};
		const dialog = new frappe.ui.Dialog({
			title: __("Video Settings"),
			fields: [
				{
					fieldname: "total_duration_seconds",
					fieldtype: "Float",
					label: __("Duration (seconds)"),
					default: settings.total_duration_seconds || 8,
					reqd: 1,
				},
				{
					fieldname: "delivery_preset",
					fieldtype: "Select",
					label: __("Format"),
					options: "Landscape\nPortrait\nSquare",
					default: settings.delivery_preset || "Landscape",
					reqd: 1,
				},
			],
			primary_action_label: __("Save"),
			primary_action(values) {
				dialog.hide();
				frm.call("save_video_settings", values, (save_response) => {
					if (save_response.exc) return;
					frm.reload_doc().then(() => {
						frappe.show_alert({
							message: __("Video Settings saved."),
							indicator: "green",
						});
						if (after_save) after_save();
					});
				});
			},
		});
		dialog.show();
	});
}

function generate_project_video(frm) {
	frappe.call({
		method: "joymedia.joymedia.doctype.media_project.media_project.generate_project_video",
		args: { project_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Generating video..."),
		callback(r) {
			if (r.exc || !r.message) return;
			frm.reload_doc();
			frappe.show_alert({
				message: __("Video generation started."),
				indicator: "green",
			});
		},
	});
}

function retry_failed_generation(frm) {
	frm.call("retry_failed_jobs", {}, (r) => {
		if (r.exc || !r.message) return;
		frm.reload_doc();
		frappe.show_alert({
			message: __("Failed video generation was queued again."),
			indicator: "green",
		});
	});
}
