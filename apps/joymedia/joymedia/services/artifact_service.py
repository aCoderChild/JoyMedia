# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

from pathlib import Path

import frappe
from frappe import _


def get_attempt_artifact(attempt_name, artifact_role):
	name = frappe.db.get_value(
		"Generation Artifact",
		{
			"generation_attempt": attempt_name,
			"artifact_role": artifact_role,
		},
		"name",
	)
	return frappe.get_doc("Generation Artifact", name) if name else None


@frappe.whitelist()
def stream_artifact(artifact_name: str):
	"""Return an inline preview of a temporary generated video artifact."""
	frappe.has_permission("Generation Artifact", "read", artifact_name, throw=True)
	return stream_artifact_internal(artifact_name)


def stream_artifact_internal(artifact_name: str):
	artifact = frappe.get_doc("Generation Artifact", artifact_name)
	if artifact.media_type != "Video":
		frappe.throw(_("Only video artifacts can currently be previewed."))

	if artifact.frappe_file:
		file_doc = frappe.get_doc("File", {"file_url": artifact.frappe_file})
		frappe.local.response.filename = Path(file_doc.file_name).name
		frappe.local.response.filecontent = file_doc.get_content()
		frappe.local.response.content_type = "video/mp4"
		frappe.local.response.display_content_as = "inline"
		frappe.local.response.type = "download"
		return

	if not artifact.frappe_file:
		frappe.throw(_("Generation Artifact {0} has no available video file.").format(artifact.name))
