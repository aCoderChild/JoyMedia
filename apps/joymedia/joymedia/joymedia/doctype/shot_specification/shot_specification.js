frappe.ui.form.on("Shot Specification", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(
			__("Compile Prompt"),
			() => {
				frappe.prompt(
					[
						{
							label: __("Prompt Template Version"),
							fieldname: "prompt_template_version",
							fieldtype: "Link",
							options: "Prompt Template Version",
							reqd: 1,
							get_query() {
								return {
									filters: {
										status: ["in", ["Testing", "Production"]],
									},
								};
							},
						},
					],
					(values) => {
						frappe.call({
							method: "joymedia.joymedia.services.prompt_compiler.compile_prompt_from_ui",
							args: {
								shot_specification: frm.doc.name,
								prompt_template_version: values.prompt_template_version,
							},
							freeze: true,
							freeze_message: __("Compiling prompt..."),
							callback(r) {
								if (!r.exc && r.message) {
									frappe.show_alert({
										message: __("Compiled Prompt {0} created", [r.message.name]),
										indicator: "green",
									});
									frappe.set_route("Form", "Compiled Prompt", r.message.name);
								}
							},
						});
					},
					__("Compile Prompt"),
					__("Compile")
				);
			}
		);
	},
});
