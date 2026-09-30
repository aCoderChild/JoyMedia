// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Generation Workflow", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Validate Bindings"),
			() => validate_bindings(frm),
			__("Generation Workflow")
		);
		frm.add_custom_button(
			__("Inspect Nodes"),
			() => inspect_nodes(frm),
			__("Generation Workflow")
		);
		frm.add_custom_button(
			__("Clone Revision"),
			() => clone_revision(frm),
			__("Generation Workflow")
		);
	},
});

function validate_bindings(frm) {
	frappe.call({
		method: "joymedia.joymedia.doctype.generation_workflow.generation_workflow.validate_workflow",
		args: { version_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Validating workflow bindings..."),
	}).then(() => {
		frappe.show_alert({ message: __("Workflow bindings are valid."), indicator: "green" });
	});
}

function inspect_nodes(frm) {
	frappe.call({
		method: "joymedia.joymedia.doctype.generation_workflow.generation_workflow.get_workflow_nodes",
		args: { version_name: frm.doc.name },
		freeze: true,
		freeze_message: __("Reading workflow nodes..."),
	}).then((response) => {
		const nodes = response.message?.nodes || [];
		const rows = nodes
			.map((node) => {
				const nodeKey = frappe.utils.escape_html(node.node_key || "");
				const title = frappe.utils.escape_html(node.title || node.class_type || "");
				const classType = frappe.utils.escape_html(node.class_type || "");
				const inputs = frappe.utils.escape_html((node.inputs || []).join(", "));
				return `<tr><td><code>${nodeKey}</code></td><td>${title}</td><td>${classType}</td><td><code>${inputs}</code></td></tr>`;
			})
			.join("");

		frappe.msgprint({
			title: __("Workflow Nodes"),
			wide: true,
			message: `
				<p>${__("Use these exact node keys and input names in Bindings.")}</p>
				<div style="max-height: 60vh; overflow: auto;">
					<table class="table table-bordered">
						<thead><tr><th>${__("Node Key")}</th><th>${__("Title")}</th><th>${__("Class")}</th><th>${__("Inputs")}</th></tr></thead>
						<tbody>${rows}</tbody>
					</table>
				</div>`,
		});
	});
}

function clone_revision(frm) {
	frappe.confirm(
		__("Create a new editable revision of this workflow?"),
		() => {
			frappe.call({
				method: "joymedia.joymedia.doctype.generation_workflow.generation_workflow.clone_workflow_as_draft",
				args: { version_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Creating workflow revision..."),
			}).then((response) => {
				frappe.set_route("Form", "Generation Workflow", response.message.name);
			});
		}
	);
}
