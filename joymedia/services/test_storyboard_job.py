from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services import storyboard_job


class TestStoryboardJob(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc(
			{"doctype": "Media Project", "project_name": "Planning Job", "planning_status": "Running"}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _run(self, project):
		with patch.object(storyboard_job.frappe, "get_doc", return_value=project), patch.object(
			storyboard_job.frappe.db, "rollback"
		), patch.object(storyboard_job.frappe, "log_error"):
			storyboard_job.plan_and_generate(self.project.name)
		return frappe.db.get_value("Media Project", self.project.name, ["planning_status", "planning_error"])

	@patch("joymedia.services.video_plan_service.apply_video_plan")
	@patch("joymedia.services.shot_duration_planner.recalculate_shot_durations")
	def test_planning_then_rendering_clears_the_status(self, recalculate, apply_plan):
		project = MagicMock(name=self.project.name)
		project.name = self.project.name

		self.assertEqual(("Idle", ""), self._run(project))
		apply_plan.assert_called_once()
		project.generate_video.assert_called_once()

	def test_user_facing_problems_are_shown_as_written(self):
		project = MagicMock()
		project.name = self.project.name
		project._use_reference_video_for_story_film.side_effect = frappe.ValidationError("Add at least one image.")

		self.assertEqual(("Failed", "Add at least one image."), self._run(project))

	def test_technical_failures_get_a_plain_message(self):
		project = MagicMock()
		project.name = self.project.name
		project.generate_video_plan.side_effect = KeyError("choices")

		status, error = self._run(project)
		self.assertEqual("Failed", status)
		self.assertNotIn("choices", error)

	@patch("joymedia.services.storyboard_job.is_render_alive", return_value=False)
	def test_planning_job_that_died_is_reported_failed(self, alive):
		self.assertEqual("Failed", storyboard_job.planning_status(self.project.name))
