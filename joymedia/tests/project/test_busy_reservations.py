import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.project.context import _busy_shots


class TestBusyReservations(TestCase):
	def check(self, scope, tasks=()):
		def rows(doctype, **kwargs):
			if doctype == "Generation Run":
				return [frappe._dict(name="RUN-QUEUED", execution_scope_json=json.dumps(scope))]
			if doctype == "Shot":
				return ["SCENE-A", "SCENE-B"]
			if doctype == "Generation Task":
				return list(tasks)
			self.fail(doctype)

		with patch("joymedia.services.project.context.frappe.get_all", side_effect=rows):
			return _busy_shots("PROJECT")

	def test_a_queued_scene_is_reserved_before_its_worker_has_created_tasks(self):
		self.assertEqual(["SCENE-A"], self.check({"shot_names": ["SCENE-A"]}))

	def test_a_whole_project_run_reserves_all_active_scenes_before_preparation(self):
		self.assertEqual(["SCENE-A", "SCENE-B"], self.check({}))

	def test_reservations_never_include_other_projects_scenes(self):
		self.assertEqual(["SCENE-A"], self.check({"shot_names": ["SCENE-A", "FOREIGN"]}, tasks=["FOREIGN"]))
