frappe.ui.form.on("Generation Run", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Draft") {
			return;
		}

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
});
