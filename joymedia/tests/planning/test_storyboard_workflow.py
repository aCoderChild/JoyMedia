"""The Storyboard Approval workflow must govern the field without breaking any flow the app itself uses."""

from unittest.mock import patch

import frappe
from frappe.model.workflow import WorkflowPermissionError, apply_workflow
from frappe.tests.utils import FrappeTestCase

from joymedia.api import storyboard
from joymedia.tests.editing.test_timeline import _create_workflow


class TestStoryboardApprovalWorkflow(FrappeTestCase):
	EMAIL = "workflow-client@example.com"

	def setUp(self):
		super().setUp()
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", self.EMAIL):
			user = frappe.get_doc(
				{"doctype": "User", "email": self.EMAIL, "first_name": "Client", "send_welcome_email": 0}
			)
			user.append("roles", {"role": "JoyMedia User"})
			user.insert(ignore_permissions=True)
		frappe.set_user(self.EMAIL)
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Workflow",
				"workflow": _create_workflow(),
				"total_duration_seconds": 3,
				"delivery_preset": "Landscape",
				"video_idea": "An idea",
			}
		).insert(ignore_permissions=True)
		self.shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"generation_prompt": "A scene.",
				"duration_seconds": 3.0,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def _status(self):
		return frappe.db.get_value("Media Project", self.project.name, "storyboard_approval_status")

	def test_the_workflow_is_installed_and_covers_the_three_states(self):
		workflow = frappe.get_doc("Workflow", "Storyboard Approval")
		self.assertEqual(1, workflow.is_active)
		self.assertEqual("storyboard_approval_status", workflow.workflow_state_field)
		self.assertEqual({"Draft", "Ready for Review", "Approved"}, {row.state for row in workflow.states})

	def test_a_client_can_approve_and_an_edit_reopens_approval(self):
		self.assertEqual("Draft", self._status())
		storyboard.approve_project_storyboard(self.project.name, True)
		self.assertEqual("Approved", self._status())

		# Editing an approved plan reopens it through the project controller; the workflow must allow that.
		storyboard.update_project_shot(
			self.project.name, self.shot.name, {"generation_prompt": "A changed scene."}
		)
		self.assertEqual("Ready for Review", self._status())

	def test_a_direction_edit_cannot_keep_a_contradictory_older_motion_plan(self):
		frappe.db.set_value(
			"Shot",
			self.shot.name,
			{
				"motion_plan_json": '{"actions":[{"action":"Old gesture","start":0,"end":2}]}',
				"end_state": "Old expression",
				"handoff_type": "motion_continuation",
			},
		)
		storyboard.update_project_shot(
			self.project.name,
			self.shot.name,
			{"generation_prompt": "A different gesture with an unchanged expression."},
		)
		shot = frappe.get_doc("Shot", self.shot.name)
		self.assertFalse(shot.motion_plan_json)
		self.assertFalse(shot.end_state)
		self.assertFalse(shot.handoff_type)

	def test_a_direction_edit_can_supply_new_opening_and_ending_states(self):
		storyboard.update_project_shot(
			self.project.name,
			self.shot.name,
			{
				"generation_prompt": "Open the already-held sheet once.",
				"image_prompt": "One sheet is already held outside its pack.",
				"start_state": "The actor holds one extracted sheet above the supported pack.",
				"end_state": "The same sheet is open between the actor's hands.",
			},
		)
		shot = frappe.get_doc("Shot", self.shot.name)
		self.assertIn("one extracted sheet", shot.start_state)
		self.assertIn("same sheet", shot.end_state)

	def test_the_desk_actions_move_the_state_and_leave_an_audit_trail(self):
		project = frappe.get_doc("Media Project", self.project.name)
		apply_workflow(project, "Submit for review")
		self.assertEqual("Ready for Review", self._status())
		apply_workflow(frappe.get_doc("Media Project", self.project.name), "Approve")
		self.assertEqual("Approved", self._status())

	def test_explicit_reconfirmation_preserves_plan_when_image_direction_changes(self):
		plan = {"actions": [{"action": "Move", "start": 0, "end": 3}]}
		storyboard.update_project_shot(self.project.name, self.shot.name, {"motion_plan_json": plan})
		response = storyboard.update_project_shot(
			self.project.name,
			self.shot.name,
			{
				"image_prompt": "A reachable starting pose.",
				"motion_plan_json": plan,
			},
		)
		self.assertEqual(frappe.parse_json(response["motion_plan_json"]), plan)
		self.assertEqual(
			frappe.parse_json(frappe.db.get_value("Shot", self.shot.name, "motion_plan_json")), plan
		)

	def test_a_jump_the_workflow_does_not_define_is_refused(self):
		storyboard.approve_project_storyboard(self.project.name, True)
		project = frappe.get_doc("Media Project", self.project.name)
		project.storyboard_approval_status = "Draft"  # Approved -> Draft is not a defined transition
		with self.assertRaises(WorkflowPermissionError):
			project.save()
