from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.api.studio_tools import effects_status, queue_effects, run_effects, set_export_quality


class TestStudioTools(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Studio tools test",
				"product_name": "Sample",
				"video_idea": "A scene.",
				"total_duration_seconds": 5,
				"delivery_preset": "Landscape",
				"delivery_width": 1280,
				"delivery_height": 720,
			}
		).insert(ignore_permissions=True)

	def test_export_preset_preserves_generation_settings_and_blocks_active_export(self):
		workflow = self.project.workflow
		set_export_quality(self.project.name, "Studio 1440p60")
		self.project.reload()
		self.assertEqual("Studio 1440p60", self.project.export_quality)
		self.assertEqual(workflow, self.project.workflow)
		with self.assertRaises(frappe.ValidationError):
			set_export_quality(self.project.name, "4K")
		self.project.db_set("export_status", "Running", update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			set_export_quality(self.project.name, "Draft 720p")

	def test_sfx_queues_in_background_and_reuses_pending_request(self):
		shot = SimpleNamespace(
			media_project=self.project.name,
			name="test-shot",
			is_removed=False,
			selected_output_asset_version="rendered-video",
		)
		get_doc = frappe.get_doc
		with (
			patch.object(
				frappe, "get_doc", side_effect=lambda dt, name: shot if dt == "Shot" else get_doc(dt, name)
			),
			patch("joymedia.api.studio_tools.capabilities", return_value={"effects": True}),
			patch("frappe.utils.background_jobs.get_job", return_value=None) as get_job,
			patch.object(frappe, "enqueue") as enqueue,
		):
			request = queue_effects(self.project.name, shot.name, "paper rustling", request_id="request-1")
			self.assertEqual("long", enqueue.call_args.kwargs["queue"])
			self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
			enqueue.reset_mock()
			get_job.return_value = Mock(get_status=Mock(return_value="queued"))
			self.assertEqual(
				request, queue_effects(self.project.name, shot.name, "paper rustling", request_id="request-1")
			)
			enqueue.assert_not_called()

	def test_effects_status_rejects_other_project_job(self):
		with self.assertRaises(frappe.PermissionError):
			effects_status(self.project.name, "joymedia-sfx-another-project-123")

	def test_sfx_does_not_attach_to_a_take_changed_during_generation(self):
		with (
			patch.object(frappe.db, "get_value", side_effect=["original-video", "new-video"]),
			patch(
				"joymedia.services.audio.plan.generate_cue_audio",
				return_value={"asset_version": "generated-audio"},
			),
			patch("joymedia.services.audio.plan.place_cue_audio") as place,
		):
			with self.assertRaises(frappe.ValidationError):
				run_effects(self.project.name, "shot", "rustling", "Administrator", "original-video")
			place.assert_not_called()
