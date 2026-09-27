// Copyright (c) 2026, JoyMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Quality Review", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.generation_artifact) return;

		add_preview_button(frm);

		if (frm.doc.status === "Pending") {
			add_approve_button(frm);
			add_reject_button(frm);
		}

		if (frm.doc.status === "Rejected") add_regenerate_button(frm);
	},
});

function add_preview_button(frm) {
	frappe.db
		.get_value("Generation Artifact", frm.doc.generation_artifact, "lifecycle_status")
		.then(({ message }) => {
			if (!message || message.lifecycle_status !== "Temporary") return;

			frm.add_custom_button(
				__("Preview Artifact"),
				() => show_artifact_preview(frm),
				__("Review")
			);
		});
}

function add_approve_button(frm) {
	frm.add_custom_button(__("Approve"), () => {
		frappe.confirm(__("Approve this generated shot?"), () => {
			frappe.call({
				method: "joymedia.joymedia.doctype.quality_review.quality_review.approve_review",
				args: { review_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Approving..."),
				callback(r) {
					if (!r.exc) frm.reload_doc();
				},
			});
		});
	}, __("Review"));
}

function add_reject_button(frm) {
	frm.add_custom_button(__("Reject"), () => {
		frappe.prompt(
			[{ fieldname: "notes", fieldtype: "Small Text", label: __("What should be improved?") }],
			(values) => {
				frappe.call({
					method: "joymedia.joymedia.doctype.quality_review.quality_review.reject_review",
					args: { review_name: frm.doc.name, notes: values.notes },
					freeze: true,
					freeze_message: __("Rejecting..."),
					callback(r) {
						if (!r.exc) frm.reload_doc();
					},
				});
			},
			__("Reject Shot"),
			__("Reject")
		);
	}, __("Review"));
}

function add_regenerate_button(frm) {
	frm.add_custom_button(__("Regenerate Shot"), () => regenerate_shot(frm), __("Review"));
}

function show_artifact_preview(frm) {
	const preview_url =
		"/api/method/joymedia.services.artifact_service.stream_review_artifact?quality_review_name=" +
		encodeURIComponent(frm.doc.name);
	const dialog = new frappe.ui.Dialog({
		title: __("Temporary Generation Preview"),
		fields: [{ fieldtype: "HTML", fieldname: "artifact_preview" }],
	});
	dialog.fields_dict.artifact_preview.$wrapper.html(
		`<video controls preload="metadata" style="max-width: 100%; width: 100%;">
			<source src="${preview_url}" type="video/mp4">
			${__("Your browser does not support video playback.")}
		</video>`
	);
	dialog.show();
}

function regenerate_shot(frm) {
	frappe.prompt(
		[
			{
				fieldname: "reason",
				fieldtype: "Select",
				label: __("Retry Reason"),
				options: "Human Review Rejection\nQA Failure",
				default: "Human Review Rejection",
				reqd: 1,
			},
		],
		(values) => {
			frappe.call({
				method: "joymedia.joymedia.doctype.quality_review.quality_review.regenerate_shot_from_ui",
				args: { quality_review_name: frm.doc.name, reason: values.reason },
				freeze: true,
				freeze_message: __("Creating and submitting QA retry..."),
				callback(r) {
					if (!r.exc && r.message?.name) frappe.set_route("Form", "Generation Attempt", r.message.name);
				},
			});
		},
		__("Regenerate Shot"),
		__("Regenerate")
	);
}
