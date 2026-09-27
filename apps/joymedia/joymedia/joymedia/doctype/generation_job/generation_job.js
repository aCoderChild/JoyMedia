// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Generation Job", {
	refresh(frm) {
		if (frm.is_new() || !["Failed", "Partially Completed"].includes(frm.doc.status)) {
			return;
		}

		frm.add_custom_button("Retry Failed Attempts", () => {
			frappe.prompt(
				[
					{
						fieldname: "reason",
						fieldtype: "Select",
						label: "Retry Reason",
						options:
							"Execution Failure\nQA Failure\nHuman Review Rejection\nPrompt Revision\nWorkflow Revision\nInput Revision\nOther",
						default: "Execution Failure",
						reqd: 1
					}
				],
				(values) => {
					frappe.call({
						method: "joymedia.services.generation_orchestrator.retry_generation_job_from_ui",
						args: { job_name: frm.doc.name, reason: values.reason },
						freeze: true,
						freeze_message: "Creating and submitting retry attempts...",
						callback(r) {
							if (!r.exc) {
								frm.reload_doc();
							}
						}
					});
				},
				"Retry Failed Attempts",
				"Retry and Submit"
			);
		}, "Execution");
	}
});
