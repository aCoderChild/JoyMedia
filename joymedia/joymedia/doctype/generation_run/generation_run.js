frappe.ui.form.on("Generation Run", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.status === "Draft") {
			frm.add_custom_button("Start Run", () => {
				frappe.call({
					method: "joymedia.services.generation_orchestrator.start_run",
					args: { run_name: frm.doc.name },
					freeze: true,
					freeze_message: "Starting generation run...",
					callback(r) {
						if (!r.exc) {
							frm.reload_doc();
						}
					}
				});
			}, "Generation");
		}

		if (frm.doc.status === "Ready for Composition") {
			frm.add_custom_button("Compose Final Video", () => {
				frappe.call({
					method: "joymedia.services.generation_orchestrator.finalize_run_from_ui",
					args: { run_name: frm.doc.name },
					freeze: true,
					freeze_message: "Composing final video...",
					callback(r) {
						if (!r.exc) {
							frm.reload_doc();
						}
					}
				});
			}, "Delivery");
		}
	}
});
