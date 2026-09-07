// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Generation Artifact", {
	refresh(frm) {
		if (
			frm.is_new() ||
			!["Temporary", "Retained"].includes(frm.doc.lifecycle_status)
		) {
			return;
		}

		frm.add_custom_button(
			__("Promote to Media Asset"),
			() => {
				frappe.confirm(
					__("Promote this raw generation artifact to a permanent Media Asset?"),
					() => {
						frappe.call({
							method:
								"joymedia.services.artifact_service.promote_artifact_from_ui",
							args: {
								artifact_name: frm.doc.name,
							},
							freeze: true,
							freeze_message: __("Promoting artifact..."),
							callback(r) {
								if (!r.exc && r.message?.asset_version) {
									frappe.show_alert({
										message: __("Created {0}", [r.message.asset_version]),
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
