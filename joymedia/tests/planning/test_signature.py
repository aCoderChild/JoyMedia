from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning.signature import assert_plan_matches_approval, compute_plan_signature
from joymedia.tests.editing.test_timeline import _create_workflow


class TestPlanSignature(FrappeTestCase):
	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Plan Signature",
				"workflow": _create_workflow(),
				"total_duration_seconds": 2,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)
		self.shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"generation_prompt": "A scene.",
				"duration_seconds": 2.0,
				"caption": "Hello",
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_caption_and_voice_over_do_not_change_the_signature(self):
		before = compute_plan_signature(self.project.name)
		self.shot.db_set({"caption": "New claim", "voice_over": "New line", "audio_cues": "SFX"})
		self.assertEqual(before, compute_plan_signature(self.project.name))

	def test_prompt_continuity_and_reference_changes_do_change_it(self):
		before = compute_plan_signature(self.project.name)
		self.shot.db_set("generation_prompt", "A different scene.")
		changed_prompt = compute_plan_signature(self.project.name)
		self.assertNotEqual(before, changed_prompt)
		self.shot.db_set("duration_seconds", 3.0)
		self.assertNotEqual(changed_prompt, compute_plan_signature(self.project.name))

	def test_generation_is_refused_after_the_approved_plan_changes(self):
		self.project.db_set("storyboard_approval_status", "Approved")
		self.project.db_set("approved_plan_signature", compute_plan_signature(self.project.name))
		assert_plan_matches_approval(frappe.get_doc("Media Project", self.project.name))
		self.shot.db_set("generation_prompt", "Edited after approval.")
		with self.assertRaises(frappe.ValidationError):
			assert_plan_matches_approval(frappe.get_doc("Media Project", self.project.name))
		self.assertEqual(
			"Ready for Review",
			frappe.db.get_value("Media Project", self.project.name, "storyboard_approval_status"),
		)


class TestRetryPolicy(FrappeTestCase):
	def _run(self, signature):
		return frappe._dict(
			media_project="P", execution_scope_json=frappe.as_json({"plan_signature": signature})
		)

	def test_retry_is_refused_after_the_plan_changed(self):
		from joymedia.services.generation.orchestrator import _require_run_plan_unchanged

		with patch("joymedia.services.planning.signature.compute_plan_signature", return_value="new"):
			with self.assertRaises(frappe.ValidationError):
				_require_run_plan_unchanged(self._run("old"))
			_require_run_plan_unchanged(self._run("new"))

	def test_runs_without_a_recorded_signature_can_still_retry(self):
		from joymedia.services.generation.orchestrator import _require_run_plan_unchanged

		_require_run_plan_unchanged(frappe._dict(media_project="P", execution_scope_json="{}"))
