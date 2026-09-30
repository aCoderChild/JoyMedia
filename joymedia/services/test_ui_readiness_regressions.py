from contextlib import nullcontext
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.joymedia.doctype.generation_attempt.generation_attempt import (
	_invalidate_manual_regeneration_outputs,
)
from joymedia.joymedia.doctype.media_specification.media_specification import MediaSpecification
from joymedia.services.generation_runner import submit_attempt


class TestUIReadinessRegressions(FrappeTestCase):
	def test_chained_reroll_attempt_waits_for_new_upstream_output(self):
		attempt = frappe._dict(
			name="ATT-DOWNSTREAM",
			status="Pending",
			generation_job="JOB-DOWNSTREAM",
		)
		job = frappe._dict(
			name="JOB-DOWNSTREAM",
			depends_on_job="JOB-UPSTREAM",
		)

		with (
			patch(
				"joymedia.services.generation_runner.filelock",
				return_value=nullcontext(),
			),
			patch(
				"joymedia.services.generation_runner.frappe.get_doc",
				side_effect=[attempt, job],
			),
			patch(
				"joymedia.services.generation_runner.attach_chained_first_frame",
				return_value=False,
			),
			patch("joymedia.services.generation_runner.submit_workflow") as submit_workflow,
		):
			result = submit_attempt(attempt.name)

		self.assertEqual(
			result,
			{"deferred": True, "dependency": "JOB-UPSTREAM"},
		)
		submit_workflow.assert_not_called()
		self.assertEqual(attempt.status, "Pending")

	def test_manual_regeneration_invalidates_stale_final_outputs(self):
		job = frappe._dict(name="JOB-00001", generation_run="RUN-00001")
		run = frappe._dict(name="RUN-00001", media_specification="SPEC-00001")

		with (
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.get_doc",
				return_value=run,
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.db.get_value",
				return_value="PROJECT-00001",
			),
			patch(
				"joymedia.joymedia.doctype.generation_attempt.generation_attempt.frappe.db.set_value"
			) as set_value,
			patch(
				"joymedia.services.timeline_editor._invalidate_project_output"
			) as invalidate_project_output,
		):
			_invalidate_manual_regeneration_outputs(job)

		set_value.assert_called_once_with(
			"Generation Run",
			"RUN-00001",
			{
				"final_asset_version": None,
				"completed_at": None,
				"failure_class": None,
				"error_summary": None,
			},
			update_modified=False,
		)
		invalidate_project_output.assert_called_once_with("PROJECT-00001")

	def test_new_storyboard_revision_inherits_generation_context(self):
		specification = frappe.new_doc("Media Specification")
		specification.media_project = "PROJECT-00001"
		specification.version_number = 2
		specification.continuity_mode = "Multi-shot"
		specification.workflow = ""
		specification.video_style = ""
		specification.total_duration_seconds = 0
		specification.delivery_preset = ""
		specification.planning_context_json = ""
		specification.planning_context_hash = ""

		previous = frappe._dict(
			name="SPEC-00001",
			workflow="WORKFLOW-00001",
			video_style="product_showcase",
			continuity_mode="Continuous",
			total_duration_seconds=30,
			delivery_preset="Portrait",
			delivery_width=768,
			delivery_height=1344,
			generation_instructions="",
			global_consistency_instructions="",
			planning_context_json='{"video_idea":"cinematic"}',
			planning_context_hash="planning-hash",
			audio_cues=[
				frappe._dict(
					role="BGM",
					asset_version="ASTV-00001",
					start_seconds=0,
					end_seconds=30,
					gain_db=-3,
					fade_in_seconds=1,
					fade_out_seconds=1,
					duck_others=0,
				)
			],
		)

		with (
			patch(
				"joymedia.joymedia.doctype.media_specification.media_specification.frappe.get_all",
				return_value=[frappe._dict(name=previous.name)],
			),
			patch(
				"joymedia.joymedia.doctype.media_specification.media_specification.frappe.get_doc",
				return_value=previous,
			),
		):
			MediaSpecification._inherit_revision_state(specification)

		self.assertEqual(specification.workflow, "WORKFLOW-00001")
		self.assertEqual(specification.video_style, "product_showcase")
		self.assertEqual(specification.continuity_mode, "Continuous")
		self.assertEqual(specification.total_duration_seconds, 30)
		self.assertEqual(specification.delivery_preset, "Portrait")
		self.assertEqual(specification.planning_context_hash, "planning-hash")
		self.assertEqual(
			specification.planning_context_json,
			'{"video_idea":"cinematic"}',
		)
		self.assertEqual(len(specification.audio_cues), 1)
		self.assertEqual(specification.audio_cues[0].role, "BGM")
