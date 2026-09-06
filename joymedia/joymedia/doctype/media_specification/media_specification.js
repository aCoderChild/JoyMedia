// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Media Specification", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(
			__("Compose Final Video"),
			() => {
				frappe.confirm(
					__("Compose the selected shot outputs into a final video?"),
					() => {
						frappe.call({
							method:
								"joymedia.services.video_composer.compose_media_specification_from_ui",
							args: { media_specification_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Composing final video..."),
							callback(r) {
								if (r.message?.final_asset_version) {
									frappe.show_alert({
										message: __("Created {0}", [r.message.final_asset_version]),
										indicator: "green",
									});
									frm.reload_doc();
								}
							},
						});
					}
				);
			},
			__("Production")
		);
	},
});
