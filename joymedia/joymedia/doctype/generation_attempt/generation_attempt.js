// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Generation Attempt", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.status === "Pending") {
			frm.add_custom_button("Submit to ComfyUI", () => {
				frappe.confirm("Submit this generation attempt to ComfyUI?", () => {
					frappe.call({
						method: "joymedia.services.generation_runner.submit_attempt_from_ui",
						args: { attempt_name: frm.doc.name },
						freeze: true,
						freeze_message: "Submitting to ComfyUI...",
						callback(r) {
							if (!r.exc) {
								frm.reload_doc();
							}
						}
					});
				});
			}, "Execution");
		}

		if (frm.doc.status === "Failed") {
			frm.add_custom_button("Create Retry Attempt", () => {
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
							method:
								"joymedia.joymedia.doctype.generation_attempt.generation_attempt.create_retry_attempt",
							args: {
								failed_attempt_name: frm.doc.name,
								reason: values.reason
							},
							freeze: true,
							freeze_message: "Creating retry attempt...",
							callback(r) {
								if (!r.exc && r.message?.name) {
									frappe.set_route("Form", "Generation Attempt", r.message.name);
								}
							}
						});
					},
					"Create Retry Attempt",
					"Create"
				);
			}, "Execution");
		}
	}
});
