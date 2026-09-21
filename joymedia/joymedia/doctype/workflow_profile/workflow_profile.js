// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Workflow Profile", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Workflow Versions"), () => {
			frappe.set_route("List", "Workflow Version", {
				workflow_profile: frm.doc.name,
			});
		});

		frm.add_custom_button(__("New Workflow Version"), () => {
			frappe.new_doc("Workflow Version", {
				workflow_profile: frm.doc.name,
			});
		});

		if (frm.doc.default_workflow_version) {
			frm.add_custom_button(__("Open Default Workflow"), () => {
				frappe.set_route(
					"Form",
					"Workflow Version",
					frm.doc.default_workflow_version
				);
			});
		}
	},
});
