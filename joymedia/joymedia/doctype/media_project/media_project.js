frappe.ui.form.on("Media Project", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Generate Video Plan"), () => {
			generate_video_plan(frm);
		});
	},
});

function generate_video_plan(frm) {
	frm.call("generate_video_plan", {}, (r) => {
		if (r.exc || !r.message) return;

		show_video_plan_dialog(frm, r.message);
	});
}

function show_video_plan_dialog(frm, plan) {
	const dialog = new frappe.ui.Dialog({
		title: __("Generated Video Plan"),
		fields: [
			{
				fieldname: "media_specification",
				fieldtype: "Link",
				label: __("Draft Media Specification"),
				options: "Media Specification",
				reqd: 1,
				get_query() {
					return {
						filters: {
							media_project: frm.doc.name,
							status: "Draft",
						},
					};
				},
			},
			{
				fieldname: "plan_preview",
				fieldtype: "HTML",
			},
		],
		primary_action_label: __("Apply Plan"),
		primary_action(values) {
			apply_video_plan(frm, dialog, values.media_specification, plan);
		},
	});

	const escaped_plan = frappe.utils.escape_html(JSON.stringify(plan, null, 2));

	dialog.fields_dict.plan_preview.$wrapper.html(`
		<div style="margin-top: 16px;">
			<strong>${__("Qwen Plan")}</strong>
			<pre style="
				margin-top: 8px;
				max-height: 400px;
				overflow: auto;
				padding: 12px;
				background: var(--subtle-fg);
				border-radius: 6px;
				white-space: pre-wrap;
			">${escaped_plan}</pre>
		</div>
	`);

	dialog.show();
}

function apply_video_plan(frm, dialog, media_specification, plan) {
	frappe.call({
		method: "joymedia.services.video_plan_service.apply_video_plan_from_ui",
		args: {
			media_specification_name: media_specification,
			plan_json: JSON.stringify(plan),
		},
		freeze: true,
		freeze_message: __("Creating shots..."),
		callback(r) {
			if (r.exc) return;

			dialog.hide();

			const shots = r.message?.shots || [];

			frappe.msgprint({
				title: __("Video Plan Applied"),
				indicator: "green",
				message: __("{0} shots were created.", [shots.length]),
			});
		},
	});
}
