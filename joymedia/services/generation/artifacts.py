"""Generation Artifacts: find the artifact an attempt produced by role, and stream its stored file."""

# Copyright (c) 2026, JoyMedia and contributors
# For license information, please see license.txt

import frappe


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
