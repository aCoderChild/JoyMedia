frappe.ui.form.on("Generation Attempt", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (!["Pending", "Failed"].includes(frm.doc.status)) {
			if (!["Queued", "Running"].includes(frm.doc.status)) {
				return;
			}

			frm.add_custom_button(__("Refresh ComfyUI Status"), () => {
				frappe.call({
					method: "joymedia.joymedia.services.generation_runner.sync_attempt_result_from_ui",
					args: { attempt_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Checking ComfyUI status..."),
					callback(r) {
						if (!r.exc) {
							frm.reload_doc();
						}
					},
				});
			});
			return;
		}

		frm.add_custom_button(
			__("Submit to ComfyUI"),
			() => {
				frappe.confirm(
					__("Submit this generation attempt to ComfyUI?"),
					() => {
						frappe.call({
							method: "joymedia.joymedia.services.generation_runner.submit_attempt_from_ui",
							args: { attempt_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Uploading inputs and submitting to ComfyUI..."),
							callback(r) {
								if (!r.exc) {
									frm.reload_doc();
									frappe.show_alert({
										message: __("Submitted to ComfyUI"),
										indicator: "green",
									});
								}
							},
						});
					}
				);
			}
		);
	},
});
