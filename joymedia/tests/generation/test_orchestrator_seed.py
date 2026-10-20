from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation import orchestrator


class TestInitialSeed(FrappeTestCase):
	def test_the_first_frames_of_one_run_share_a_seed_and_videos_do_not(self):
		image, video = frappe._dict(workflow="WF-I"), frappe._dict(workflow="WF-V")
		kinds = {"WF-I": "Image", "WF-V": "Video"}
		with patch.object(
			frappe.db,
			"get_value",
			side_effect=lambda doctype, name, field: kinds[name]
			if doctype == "Generation Workflow"
			else None,
		):
			first = orchestrator._initial_seed(frappe._dict(image, generation_run="RUN-1"))
			self.assertEqual(first, orchestrator._initial_seed(frappe._dict(image, generation_run="RUN-1")))
			self.assertNotEqual(
				first, orchestrator._initial_seed(frappe._dict(image, generation_run="RUN-2"))
			)
			with patch.object(orchestrator, "_new_seed", return_value=7):
				self.assertEqual(7, orchestrator._initial_seed(frappe._dict(video, generation_run="RUN-1")))

	def test_authored_artwork_can_replay_image_noise_without_reusing_a_video_seed(self):
		for seed in (0, 1053216906):
			with patch.object(
				frappe.db,
				"get_value",
				side_effect=lambda dt, name, field: "Image"
				if dt == "Generation Workflow"
				else frappe.as_json({"keyframe_seed": seed}),
			):
				self.assertEqual(
					seed, orchestrator._initial_seed(frappe._dict(workflow="WF-I", generation_run="RUN-2"))
				)
		for seed in (True, -1, 2_147_483_648, 1.5):
			with (
				patch.object(
					frappe.db,
					"get_value",
					side_effect=lambda dt, name, field: "Image"
					if dt == "Generation Workflow"
					else frappe.as_json({"keyframe_seed": seed}),
				),
				self.assertRaises(ValueError),
			):
				orchestrator._initial_seed(frappe._dict(workflow="WF-I", generation_run="RUN-2"))
