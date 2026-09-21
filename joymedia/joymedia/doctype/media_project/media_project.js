frappe.ui.form.on("Media Project", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Assets"), () => {
			frappe.set_route("List", "Media Asset", {
				media_project: frm.doc.name,
			});
		});

		frm.add_custom_button(__("Storyboard"), () => {
			open_latest_storyboard(frm);
		});

		frm.add_custom_button(__("Review Videos"), () => {
			show_campaign_reviews(frm);
		});

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Generate Storyboard"), () => {
				generate_video_plan(frm);
			});

			frm.add_custom_button(__("Generate Video"), () => {
				show_generate_video_dialog(frm);
			});
		}

		if (["Review", "Needs Attention", "Completed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Revise Storyboard"), () => {
				create_storyboard_revision(frm);
			});
		}
	},
});

function generate_video_plan(frm) {
	show_plan_request_dialog(frm);
}

function open_latest_storyboard(frm) {
	frappe.db
		.get_list("Media Specification", {
			filters: { media_project: frm.doc.name },
			fields: ["name"],
			order_by: "version_number desc",
			limit: 1,
		})
		.then((specifications) => {
			if (!specifications.length) {
				frappe.msgprint(__("This Campaign has no Video Settings yet."));
				return;
			}

			return frappe.db.get_list("Shot Specification", {
				filters: { media_specification: specifications[0].name },
				fields: [
					"shot_number",
					"camera_direction",
					"subject_identity",
					"action_plot",
					"environment",
					"audio_direction",
				],
				order_by: "shot_number asc",
			});
		})
		.then((shots) => {
			if (!shots) return;
			if (!shots.length) {
				frappe.msgprint({
					title: __("Storyboard"),
					message: __("No storyboard has been generated yet."),
					primary_action: {
						label: __("Generate Storyboard"),
						action() {
							generate_video_plan(frm);
						},
					},
				});
				return;
			}
			const plan = {
				shots: shots.map((shot) => ({
					shot_number: shot.shot_number,
					camera: shot.camera_direction,
					subject: shot.subject_identity,
					motion: shot.action_plot,
					lighting: shot.environment,
					audio: shot.audio_direction,
				})),
			};
			const dialog = new frappe.ui.Dialog({
				title: __("Storyboard"),
				fields: [{ fieldtype: "HTML", fieldname: "storyboard" }],
				primary_action_label: __("Close"),
				primary_action() {
					dialog.hide();
				},
			});
			dialog.fields_dict.storyboard.$wrapper.html(render_storyboard(plan));
			dialog.show();
		});
}

function show_campaign_reviews(frm) {
	frm.call("get_pending_reviews", {}, (r) => {
		if (r.exc) return;
		const reviews = r.message || [];
		if (!reviews.length) {
			frappe.msgprint(__("This Campaign has no pending video reviews."));
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Review Videos"),
			fields: [{ fieldtype: "HTML", fieldname: "reviews" }],
			primary_action_label: __("Close"),
			primary_action() {
				dialog.hide();
			},
		});
		dialog.fields_dict.reviews.$wrapper.html(
			reviews
				.map(
					(review) => `
						<div style="margin-bottom: 24px;">
							<video controls preload="metadata" style="max-width: 100%; width: 100%;">
								<source src="${review.preview_url}" type="video/mp4">
								${__("Your browser does not support video playback.")}
							</video>
							<div style="margin-top: 8px;">
								<button class="btn btn-primary joymedia-approve-review" data-review="${review.name}">${__("Approve")}</button>
								<button class="btn btn-secondary joymedia-regenerate-review" data-review="${review.name}">${__("Regenerate Shot")}</button>
							</div>
						</div>
					`
				)
				.join("")
		);
		dialog.fields_dict.reviews.$wrapper.on("click", ".joymedia-approve-review", (event) => {
			approve_campaign_review(frm, dialog, event.currentTarget.dataset.review);
		});
		dialog.fields_dict.reviews.$wrapper.on("click", ".joymedia-regenerate-review", (event) => {
			regenerate_campaign_review(frm, dialog, event.currentTarget.dataset.review);
		});
		dialog.show();
	});
}

function approve_campaign_review(frm, dialog, review_name) {
	frappe.call({
		method: "joymedia.joymedia.doctype.quality_review.quality_review.approve_review",
		args: { review_name },
		freeze: true,
		freeze_message: __("Approving video..."),
		callback(r) {
			if (r.exc) return;
			dialog.hide();
			frm.reload_doc();
		},
	});
}

function regenerate_campaign_review(frm, dialog, review_name) {
	frappe.call({
		method: "joymedia.joymedia.doctype.quality_review.quality_review.reject_review",
		args: { review_name, notes: "Regenerated from Campaign review." },
		freeze: true,
		freeze_message: __("Rejecting video..."),
		callback(r) {
			if (r.exc) return;
			frappe.call({
				method: "joymedia.joymedia.doctype.quality_review.quality_review.regenerate_shot_from_ui",
				args: { quality_review_name: review_name, reason: "Human Review Rejection" },
				freeze: true,
				freeze_message: __("Regenerating shot..."),
				callback(retry_response) {
					if (retry_response.exc) return;
					dialog.hide();
					frm.reload_doc();
				},
			});
		},
	});
}

function create_storyboard_revision(frm) {
	frm.call("create_storyboard_revision", {}, (r) => {
		if (r.exc || !r.message) return;
		frm.reload_doc().then(() => show_plan_request_dialog(frm));
	});
}

function show_plan_request_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Generate Storyboard"),
		fields: [
			{
				fieldname: "scene_count",
				fieldtype: "Int",
				label: __("Number of Scenes"),
				default: 3,
				reqd: 1,
			},
		],
		primary_action_label: __("Generate Storyboard"),
		primary_action(values) {
			generate_video_plan_request(frm, dialog, values.scene_count);
		},
	});

	dialog.show();
}

function generate_video_plan_request(frm, request_dialog, scene_count) {
	request_dialog.hide();
	frm.call(
		"generate_video_plan",
		{
			scene_count,
		},
		(r) => {
			if (r.exc || !r.message) return;

			show_video_plan_dialog(frm, scene_count, r.message);
		}
	);
}

function show_video_plan_dialog(frm, scene_count, plan) {
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
			apply_video_plan(frm, dialog, plan);
		},
		secondary_action_label: __("Regenerate Plan"),
		secondary_action() {
			regenerate_video_plan(frm, dialog, scene_count);
		},
	});

	dialog.fields_dict.plan_preview.$wrapper.html(render_storyboard(plan));

	dialog.show();
}

function regenerate_video_plan(frm, dialog, scene_count) {
	dialog.hide();
	frm.call(
		"generate_video_plan",
		{
			scene_count,
		},
		(r) => {
			if (r.exc || !r.message) return;
			show_video_plan_dialog(frm, scene_count, r.message);
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

function apply_video_plan(frm, dialog, plan) {
	frappe.call({
		method: "joymedia.joymedia.doctype.media_project.media_project.apply_video_plan",
		args: {
			plan_json: JSON.stringify(plan),
		},
		freeze: true,
		freeze_message: __("Creating shots..."),
		callback(r) {
			if (r.exc) return;

			dialog.hide();
			frm.reload_doc();

			const shots = r.message?.shots || [];

			frappe.msgprint({
				title: __("Video Plan Applied"),
				indicator: "green",
				message: __("{0} shots were created.", [shots.length]),
			});
		},
	});
}

function show_generate_video_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Generate Video"),
		fields: [{ fieldtype: "HTML", fieldname: "confirmation" }],
		primary_action_label: __("Generate Video"),
		primary_action(values) {
			dialog.hide();
			frm.call(
				"generate_video",
				{},
				(r) => {
					if (r.exc || !r.message) return;
					frm.reload_doc();
					frappe.show_alert({
						message: __("Video generation started."),
						indicator: "green",
					});
				}
			);
		},
	});
	dialog.fields_dict.confirmation.$wrapper.html(
		`<p>${__("Generate this storyboard now?")}</p>`
	);

	dialog.show();
}
