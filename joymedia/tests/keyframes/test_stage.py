from typing import ClassVar
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation.orchestrator import _pipeline_steps_for_segment
from joymedia.services.keyframes import stage as keyframes


def _shot(**values):
	shot = frappe._dict(
		image_prompt="A room.",
		setting_prompt="",
		generation_inputs=[],
		keyframe_status="",
		keyframe_artifact=None,
		keyframe_signature=None,
		shot_number=2,
		continuity_mode="New Scene",
	)
	shot.update(values)
	return shot


class TestKeyframeSignature(FrappeTestCase):
	def test_it_changes_with_the_prompt_the_setting_and_the_references(self):
		base = keyframes.keyframe_signature(_shot())
		self.assertEqual(base, keyframes.keyframe_signature(_shot()))
		self.assertNotEqual(base, keyframes.keyframe_signature(_shot(image_prompt="A garden.")))
		self.assertNotEqual(base, keyframes.keyframe_signature(_shot(setting_prompt="A garden.")))
		reference = frappe._dict(reference_role="Product", asset_version="AV1")
		self.assertNotEqual(base, keyframes.keyframe_signature(_shot(generation_inputs=[reference])))

	def test_only_scenes_with_their_own_opening_frame_need_a_keyframe(self):
		self.assertTrue(keyframes.starts_scene(_shot(shot_number=1, continuity_mode="Continue")))
		self.assertTrue(keyframes.starts_scene(_shot(continuity_mode="New Scene")))
		self.assertFalse(keyframes.starts_scene(_shot(continuity_mode="Continue")))


class TestApprovedKeyframe(FrappeTestCase):
	def _task(self, shot):
		values = {
			("Generation Artifact", "ART", "frappe_file"): "/private/files/k.png",
			("Generation Artifact", "ART", "generation_attempt"): "ATT",
			("Generation Attempt", "ATT", "generation_task"): "TASK",
		}
		with patch.object(
			frappe.db,
			"get_value",
			side_effect=lambda doctype, name, field: values.get((doctype, name, field)),
		):
			return keyframes.approved_keyframe_task(shot)

	def _approved(self, **values):
		shot = _shot(keyframe_status="Approved", keyframe_artifact="ART", **values)
		shot.keyframe_signature = keyframes.keyframe_signature(shot)
		return shot

	def test_an_approved_current_keyframe_is_used(self):
		self.assertEqual("TASK", self._task(self._approved()))

	def test_a_pending_keyframe_is_not_used(self):
		shot = self._approved()
		shot.keyframe_status = "Pending Review"
		self.assertIsNone(self._task(shot))

	def test_a_keyframe_drawn_for_other_inputs_is_not_used(self):
		shot = self._approved()
		shot.setting_prompt = "A different place."
		self.assertIsNone(self._task(shot))


class TestVideoStageUsesTheKeyframe(FrappeTestCase):
	steps: ClassVar[list] = [frappe._dict(step_key="keyframe"), frappe._dict(step_key="video")]

	def test_an_authored_first_frame_skips_redrawing_but_not_later_continuation(self):
		self.assertEqual(
			[(self.steps[-1], None, None, True)],
			_pipeline_steps_for_segment(self.steps, explicit_first_frame=True, keyframe_job="OLD"),
		)
		self.assertEqual(
			[(self.steps[-1], "PREVIOUS", "Last Frame", False)],
			_pipeline_steps_for_segment(
				self.steps, explicit_first_frame=True, previous_segment_job="PREVIOUS"
			),
		)
		self.assertEqual(
			[(self.steps[-1], "TAIL", "Last Frame", False)],
			_pipeline_steps_for_segment(
				self.steps,
				explicit_first_frame=True,
				cross_shot_continuity=True,
				previous_shot_tail_job="TAIL",
			),
		)

	def test_an_approved_keyframe_replaces_the_image_stage(self):
		stages = _pipeline_steps_for_segment(self.steps, keyframe_job="TASK-K")
		self.assertEqual([(self.steps[1], "TASK-K", "Primary Image", False)], stages)

	def test_later_segments_still_continue_from_the_previous_last_frame(self):
		stages = _pipeline_steps_for_segment(
			self.steps, previous_segment_job="TASK-V1", keyframe_job="TASK-K"
		)
		self.assertEqual([(self.steps[1], "TASK-V1", "Last Frame", False)], stages)

	def test_without_a_keyframe_the_full_pipeline_runs(self):
		self.assertEqual(2, len(_pipeline_steps_for_segment(self.steps)))

	def test_authored_frame_binds_declared_controls_without_reinterpreting_cast(self):
		from unittest.mock import patch

		from joymedia.services.generation.preparation import authored_video_inputs

		contract = [dict(role="first_frame", required=True), dict(role="motion_control", required=True)]
		shot = frappe._dict(
			references=[
				dict(reference_role=role, asset_version=role + "-ASSET")
				for role in ["character", "product", "first_frame", "motion_control"]
			]
		)
		with (
			patch("joymedia.services.workflows.resolver.get_workflow_input_contract", return_value=contract),
			patch("joymedia.services.generation.preparation.validate_role_input_count"),
		):
			self.assertEqual(
				authored_video_inputs(shot, frappe._dict(name="W")),
				{"first_frame": ["first_frame-ASSET"], "motion_control": ["motion_control-ASSET"]},
			)
			shot.references = shot.references[:-1]
			with self.assertRaises(ValueError):
				authored_video_inputs(shot, frappe._dict(name="W"))


class TestKeyframePictureAccess(FrappeTestCase):
	def test_a_keyframe_picture_is_attached_to_the_project_so_its_owner_can_open_it(self):
		from unittest.mock import patch

		from joymedia.services.keyframes.stage import attach_keyframe_to_project

		with patch("joymedia.services.keyframes.stage.frappe.db.set_value") as set_value:
			attach_keyframe_to_project("/private/files/frame.png", "PRJ-1")

		set_value.assert_called_once_with(
			"File",
			{"file_url": "/private/files/frame.png", "attached_to_doctype": ["!=", "Media Project"]},
			{"attached_to_doctype": "Media Project", "attached_to_name": "PRJ-1"},
			update_modified=False,
		)
