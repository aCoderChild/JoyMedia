frappe.ui.form.on("Media Project", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Generate Video Plan"), () => {
			generate_video_plan(frm);
		});
	},
});

function generate_video_plan(frm) {
	frappe.call({
		method: "frappe.client.get_count",
		args: {
			doctype: "Media Asset",
			filters: {
				media_project: frm.doc.name,
				media_type: "Image",
				status: "Active",
			},
		},
		callback(r) {
			if (r.exc) return;
			show_plan_request_dialog(frm);
		},
	});
}

function show_plan_request_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Generate Video Plan"),
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
				fieldname: "scene_count",
				fieldtype: "Int",
				label: __("Number of Scenes"),
				default: 3,
				reqd: 1,
			},
		],
		primary_action_label: __("Generate Plan"),
		primary_action(values) {
			generate_video_plan_request(frm, dialog, values.media_specification, values.scene_count);
		},
	});

	dialog.show();
}

function generate_video_plan_request(frm, request_dialog, media_specification, scene_count) {
	request_dialog.hide();
	frm.call(
		"generate_video_plan",
		{
			media_specification_name: media_specification,
			scene_count,
		},
		(r) => {
			if (r.exc || !r.message) return;

				show_video_plan_dialog(frm, media_specification, scene_count, r.message);
		}
	);
}

function show_video_plan_dialog(frm, media_specification, scene_count, plan) {
	const dialog = new frappe.ui.Dialog({
		title: __("Generated Video Plan"),
		fields: [
			{
				fieldname: "plan_preview",
				fieldtype: "HTML",
			},
		],
		primary_action_label: __("Apply Plan"),
		primary_action(values) {
			apply_video_plan(frm, dialog, media_specification, plan);
		},
		secondary_action_label: __("Regenerate Plan"),
		secondary_action() {
			regenerate_video_plan(frm, dialog, media_specification, scene_count);
		},
	});

	dialog.fields_dict.plan_preview.$wrapper.html(render_storyboard(plan));

	dialog.show();
}

function regenerate_video_plan(frm, dialog, media_specification, scene_count) {
	dialog.hide();
	frm.call(
		"generate_video_plan",
		{
			media_specification_name: media_specification,
			scene_count,
		},
		(r) => {
			if (r.exc || !r.message) return;
			show_video_plan_dialog(frm, media_specification, scene_count, r.message);
		}
	);
}

function render_storyboard(plan) {
	const shots = plan.shots || [];
	const cards = shots
		.map((shot) => {
			const reference = shot.reference_image_index
				? `<div style="margin-bottom: 12px; color: var(--text-muted);">${__("Reference image {0}", [shot.reference_image_index])}</div>`
				: "";

			return `
				<div style="padding: 16px 0; border-bottom: 1px solid var(--border-color);">
					<h4 style="margin: 0 0 12px;">${__("Shot {0}", [shot.shot_number])}</h4>
					${reference}
					${storyboard_field("Camera", shot.camera)}
					${storyboard_field("Subject", shot.subject)}
					${storyboard_field("Motion", shot.motion)}
					${storyboard_field("Lighting", shot.lighting)}
					${storyboard_field("Audio", shot.audio)}
				</div>
			`;
		})
		.join("");

	return `<div style="max-height: 520px; overflow: auto;">${cards}</div>`;
}

function storyboard_field(label, value) {
	return `
		<div style="margin: 10px 0;">
			<strong>${__(label)}</strong>
			<div style="margin-top: 4px; white-space: pre-wrap;">${frappe.utils.escape_html(value || "")}</div>
		</div>
	`;
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
