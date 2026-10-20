from unittest.mock import patch

import frappe

from joymedia.services import partners
from joymedia.services.review import feedback
from joymedia.tests.review.test_comments import ReviewCommentCase


class TestPartnerAccess(ReviewCommentCase):
	def setUp(self):
		super().setUp()
		self.user = f"partner-{frappe.generate_hash(length=10)}@example.invalid"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": self.user,
				"first_name": "Partner test",
				"send_welcome_email": 0,
				"user_type": "Website User",
			}
		).insert(ignore_permissions=True)
		self.access = frappe.get_doc(
			{
				"doctype": "Partner Access",
				"user": self.user,
				"enabled": 1,
				"allow_feedback": 1,
				"allow_generation": 0,
				"max_projects": 1,
				"max_model_jobs": 2,
				"max_duration_seconds": 30,
				"max_pixels": 1048576,
				"videos": [{"asset_version": self.one_take.name, "label": "Shared scene"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.user)

	def admin_update(self, **values):
		frappe.set_user("Administrator")
		self.access.reload()
		self.access.update(values)
		self.access.save()
		frappe.set_user(self.user)

	def test_review_only_sees_exactly_published_versions_and_no_workspace(self):
		self.assertTrue(partners.get_access()["reviewer"])
		self.assertEqual(frappe.db.get_value("User", self.user, "user_type"), "Website User")
		self.assertFalse(frappe.db.get_value("Role", partners.ROLE, "desk_access"))
		self.assertFalse(partners.get_access()["allow_generation"])
		self.assertEqual(
			[r["asset_version"] for r in partners.get_review_library()["items"]], [self.one_take.name]
		)
		self.assertIn("review_media?", feedback.get_feedback(self.project.name, self.one_take.name)["file"])
		with self.assertRaises(frappe.PermissionError):
			feedback.get_feedback(self.project.name, self.two_take.name)
		with self.assertRaises(frappe.PermissionError):
			self.project._require_read_access()
		self.assertFalse(frappe.has_permission("Media Project", "read", doc=self.project))
		self.assertFalse(frappe.has_permission("Asset Version", "read", doc=self.one_take))
		self.assertEqual(frappe.get_list("Asset Version", pluck="name"), [])

	def test_review_only_cannot_create_projects_upload_or_edit_admin_projects(self):
		from joymedia.api.projects import create_project
		from joymedia.services.intake.assets import create_media_asset

		with self.assertRaises(frappe.PermissionError):
			create_project("Blocked", "Product", "Idea")
		with self.assertRaises(frappe.PermissionError):
			create_media_asset("Blocked", "Other")
		with self.assertRaises(frappe.PermissionError):
			self.project._require_write_access()
		self.assertFalse(frappe.has_permission("Partner Access", "write", doc=self.access))

	def test_feedback_is_stored_and_other_reviewers_comments_are_not_exposed(self):
		row = feedback.add_feedback(
			self.project.name,
			self.one_take.name,
			"Brand issue",
			frappe.generate_hash(length=24),
			start_frame=1,
		)
		self.assertEqual(row["owner"], self.user)
		frappe.set_user("Administrator")
		other = feedback.add_feedback(
			self.project.name,
			self.one_take.name,
			"Internal test note",
			frappe.generate_hash(length=24),
			start_frame=1,
		)
		frappe.set_user(self.user)
		result = feedback.get_feedback(self.project.name, self.one_take.name, focused_name=other["name"])
		self.assertEqual([r["name"] for r in result["items"]], [row["name"]])
		self.assertIsNone(result["focused"])

	def test_feedback_download_and_account_revocations_apply_immediately(self):
		self.admin_update(allow_feedback=0)
		with self.assertRaises(frappe.PermissionError):
			feedback.add_feedback(
				self.project.name,
				self.one_take.name,
				"Blocked",
				frappe.generate_hash(length=24),
				start_frame=1,
			)
		with self.assertRaises(frappe.PermissionError):
			partners.require_published(self.one_take.name, download=True)
		self.admin_update(videos=[])
		with self.assertRaises(frappe.PermissionError):
			feedback.get_feedback(self.project.name, self.one_take.name)
		self.admin_update(enabled=0)
		self.assertFalse(partners.get_access()["enabled"])
		with self.assertRaises(frappe.PermissionError):
			partners.get_review_library()

	def test_enabled_testing_is_own_projects_only_and_project_limit_is_enforced(self):
		from joymedia.api.projects import create_project

		self.admin_update(allow_generation=1)
		project = create_project("Partner sandbox", "Test product", "A short video.")
		self.assertEqual(project.owner, self.user)
		project._require_write_access()
		self.assertTrue(partners.get_access(project.name)["can_open_project"])
		self.assertFalse(partners.get_access(self.project.name)["can_open_project"])
		with self.assertRaises(frappe.ValidationError):
			create_project("Too many", "Test", "Brief")
		with self.assertRaises(frappe.PermissionError):
			self.project._require_write_access()
		project.total_duration_seconds = 31
		with self.assertRaises(frappe.ValidationError):
			project.save(ignore_permissions=True)

	def test_render_budget_applies_to_background_workers_and_retries(self):
		self.admin_update(allow_generation=1)
		frappe.set_user("Administrator")
		self.project.db_set("owner", self.user, update_modified=False)
		stale_grant = frappe.get_doc("Partner Access", self.access.name)
		original = frappe.db.get_value

		def values(doctype, name, field=None, *args, **kwargs):
			if doctype == "Generation Task" and name == "quota-task":
				return "quota-run"
			if doctype == "Generation Run" and name == "quota-run":
				return self.project.name
			return original(doctype, name, field, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=values):
			partners.charge_attempt(frappe._dict(generation_task="quota-task"))
			partners.charge_attempt(frappe._dict(generation_task="quota-task"))
			with self.assertRaises(frappe.ValidationError):
				partners.charge_attempt(frappe._dict(generation_task="quota-task"))
		self.assertEqual(frappe.db.get_value("Partner Access", self.access.name, "model_jobs_used"), 2)
		stale_grant.allow_download = 1
		stale_grant.save()
		self.assertEqual(stale_grant.model_jobs_used, 2)
		self.access.db_set("allow_generation", 0)
		with self.assertRaises(frappe.PermissionError):
			partners.require_worker_generation(self.project)

	def test_admins_keep_existing_permissions_and_partners_cannot_edit_grants(self):
		frappe.set_user("Administrator")
		self.assertTrue(frappe.has_permission("Media Project", "read", doc=self.project))
		self.assertTrue(frappe.has_permission("Asset Version", "read", doc=self.one_take))
		self.assertTrue(frappe.has_permission("Partner Access", "write", doc=self.access))
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			feedback.triage_feedback("missing", "Resolved")

	def test_reviewer_cannot_be_promoted_by_mixing_client_or_internal_roles(self):
		for role in ('JoyMedia User', 'JoyMedia Specialist', 'System Manager'):
			frappe.set_user('Administrator')
			user = frappe.get_doc('User', self.user)
			user.append('roles', {'role': role})
			with self.assertRaises(frappe.ValidationError):
				user.save(ignore_permissions=True)
			self.assertNotIn(role, frappe.get_roles(self.user))

	def test_reviewer_capabilities_stay_limited_when_testing_is_enabled(self):
		self.admin_update(allow_generation=1)
		access = partners.get_access()
		self.assertEqual(access['role'], 'reviewer')
		self.assertTrue(access['can_create'])
		for capability in ('administrator', 'can_manage_reviewers', 'can_use_library', 'can_use_advanced_editor'):
			self.assertFalse(access[capability])


from unittest import TestCase
from joymedia.services.access import role_for, portal_access


class TestRoleContract(TestCase):
	def test_explicit_role_mapping_and_capabilities(self):
		for role, roles in (
			('administrator', ['System Manager']),
			('production', ['JoyMedia Specialist', 'JoyMedia User']),
			('client', ['JoyMedia User']),
			('unassigned', ['Website User']),
		):
			with self.subTest(role=role), patch.object(frappe, 'get_roles', return_value=roles):
				access = portal_access('role-test@example.invalid')
				self.assertEqual(access['role'], role)
				self.assertEqual(access['can_create'], role != 'unassigned')
				self.assertEqual(access['can_use_advanced_editor'], role in ('administrator', 'production'))
				self.assertEqual(access['can_manage_reviewers'], role == 'administrator')

	def test_legacy_reviewer_conflicts_fail_closed(self):
		for role in ('JoyMedia User', 'JoyMedia Specialist', 'System Manager'):
			self.assertEqual(role_for('test', ['JoyMedia Reviewer', role]), 'unassigned')
		self.assertEqual(role_for('Guest', ['System Manager']), 'unassigned')
		self.assertEqual(role_for('Administrator', []), 'administrator')
