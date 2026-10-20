"""Signature of the generation-affecting parts of an approved storyboard.

Approval is tied to this signature, so a change to anything that alters rendered
footage (prompts, timing, continuity, references, the pinned workflow/pipeline) is
detected at the generation boundary. Finishing-only data (captions, voice-over,
audio cues) is deliberately excluded: editing a caption must not force re-rendering.
"""

import hashlib
import json

import frappe
from frappe import _

PROJECT_FIELDS = (
	"workflow",
	"generation_pipeline",
	"delivery_width",
	"delivery_height",
	"quality_mode",
	"generation_mode",
	"storyboard_source_json",
)
# planned_frame_count is derived from duration at generation time, so it is not part of the plan.
SHOT_FIELDS = (
	"shot_number",
	"storyboard_action",
	"image_prompt",
	"generation_prompt",
	"motion_plan_json",
	"start_state",
	"end_state",
	"handoff_type",
	"continuity_mode",
	"duration_seconds",
)


def compute_plan_signature(project_name):
	project = frappe.db.get_value("Media Project", project_name, list(PROJECT_FIELDS), as_dict=True)
	shots = []
	for shot_name in frappe.get_all(
		"Shot",
		filters={"media_project": project_name, "is_removed": 0},
		pluck="name",
		order_by="shot_number asc",
	):
		shot = frappe.get_doc("Shot", shot_name)
		entry = {field: _plain(shot.get(field)) for field in SHOT_FIELDS}
		entry["references"] = sorted(
			(row.reference_role or "", row.asset_version or "") for row in shot.generation_inputs or []
		)
		shots.append(entry)
	payload = {"project": {field: _plain(project.get(field)) for field in PROJECT_FIELDS}, "shots": shots}
	return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def assert_plan_matches_approval(project):
	"""Refuse to generate from a plan that differs from the one that was approved."""
	approved = project.get("approved_plan_signature")
	# Projects approved before signatures existed have nothing to compare against.
	if approved and approved != compute_plan_signature(project.name):
		frappe.db.set_value(
			"Media Project",
			project.name,
			"storyboard_approval_status",
			"Ready for Review",
			update_modified=False,
		)
		frappe.throw(_("The storyboard changed after it was approved. Review and approve it again."))


def _plain(value):
	return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
