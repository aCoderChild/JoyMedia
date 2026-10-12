import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from joymedia.services import scene_takes
from joymedia.services.generation_orchestrator import _keeps_selected_output
from joymedia.services.test_timeline_editor import _create_output_version, _create_workflow


class TestSceneTakes(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project", "project_name": "Scene Takes", "workflow": _create_workflow(),
				"total_duration_seconds": 2, "delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)
		self.shot = frappe.get_doc(
			{
				"doctype": "Shot", "media_project": self.project.name, "shot_number": 1,
				"generation_prompt": "A scene.", "duration_seconds": 2.0,
			}
		).insert(ignore_permissions=True)
		asset = frappe.get_doc(
			{
				"doctype": "Media Asset", "asset_name": f"{self.shot.name} Output", "media_type": "Video",
				"asset_category": "Other", "asset_scope": "Project Output", "media_project": self.project.name,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		self.takes = [_create_output_version(self.project, f"take-{n}.mp4", 1, asset)[1] for n in (1, 2)]
		self.shot.db_set("selected_output_asset_version", self.takes[1].name)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_storyboard_card_knows_its_takes(self):
		self.assertEqual((2, 2), scene_takes.take_position(self.project.name, self.shot))

	@patch("joymedia.services.post_production.resume_post_production_if_approved", return_value={"status": "Awaiting QA"})
	def test_selecting_an_unapproved_take_keeps_selection_and_waits_for_qa(self, resume):
		result = scene_takes.select_scene_take(self.project.name, self.shot.name, 1)

		self.assertEqual(self.takes[0].name, frappe.db.get_value("Shot", self.shot.name, "selected_output_asset_version"))
		self.assertEqual({"shot_name": self.shot.name, "take_count": 2, "take_index": 1, "finishing": "Awaiting QA"}, result)
		resume.assert_called_once_with(self.project.name)
		with self.assertRaises(frappe.ValidationError):
			scene_takes.select_scene_take(self.project.name, self.shot.name, 3)

	def test_regenerate_run_replaces_the_take_selected_before_it_started_once(self):
		scope = json.dumps({"shot_names": [self.shot.name], "replace_selection": True})
		started_later = frappe._dict(execution_scope_json=scope, creation=add_to_date(now_datetime(), minutes=1))
		started_earlier = frappe._dict(execution_scope_json=scope, creation=add_to_date(now_datetime(), minutes=-1))
		whole_regeneration = frappe._dict(
			execution_scope_json=json.dumps({"replace_selection": True}),
			creation=add_to_date(now_datetime(), minutes=1),
		)

		# The take was selected before the run started: the run's new take replaces it.
		self.assertFalse(_keeps_selected_output(started_later, self.shot.name))
		# The run already replaced it: keep the new take.
		self.assertTrue(_keeps_selected_output(started_earlier, self.shot.name))
		# Whole-video regeneration also replaces its prior chosen take.
		self.assertFalse(_keeps_selected_output(whole_regeneration, self.shot.name))

	@patch("joymedia.services.project_context._busy_shots")
	def test_only_a_scene_that_is_rendering_is_blocked(self, busy):
		busy.return_value = [self.shot.name]
		with self.assertRaises(frappe.ValidationError):
			scene_takes.select_scene_take(self.project.name, self.shot.name, 1)

		busy.return_value = ["SHOT-OTHER"]
		with patch("joymedia.services.post_production.resume_post_production_if_approved", return_value={"status": "Awaiting QA"}):
			self.assertEqual(1, scene_takes.select_scene_take(self.project.name, self.shot.name, 1)["take_index"])
