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

	@patch("joymedia.services.post_production.queue_post_production_internal")
	def test_selecting_an_earlier_take_uses_it_and_refinishes_the_film(self, finish):
		result = scene_takes.select_scene_take(self.project.name, self.shot.name, 1)

		self.assertEqual(self.takes[0].name, frappe.db.get_value("Shot", self.shot.name, "selected_output_asset_version"))
		self.assertEqual({"shot_name": self.shot.name, "take_count": 2, "take_index": 1}, result)
		finish.assert_called_once_with(self.project.name)
		with self.assertRaises(frappe.ValidationError):
			scene_takes.select_scene_take(self.project.name, self.shot.name, 3)

	def test_regenerate_run_replaces_the_take_selected_before_it_started_once(self):
		scope = json.dumps({"shot_names": [self.shot.name], "replace_selection": True})
		started_later = frappe._dict(execution_scope_json=scope, creation=add_to_date(now_datetime(), minutes=1))
		started_earlier = frappe._dict(execution_scope_json=scope, creation=add_to_date(now_datetime(), minutes=-1))
		full_run = frappe._dict(execution_scope_json="{}", creation=add_to_date(now_datetime(), minutes=1))

		# The take was selected before the run started: the run's new take replaces it.
		self.assertFalse(_keeps_selected_output(started_later, self.shot.name))
		# The run already replaced it: keep the new take.
		self.assertTrue(_keeps_selected_output(started_earlier, self.shot.name))
		# A normal run never replaces a chosen take.
		self.assertTrue(_keeps_selected_output(full_run, self.shot.name))
