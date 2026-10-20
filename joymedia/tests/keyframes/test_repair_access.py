from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.consistency.repair import queue_source_art_repair, _validate_source_take
from joymedia.services.editing.access import _require_asset_version_access


class TestRepairAccess(TestCase):
	def test_unselected_repair_source_must_belong_to_the_same_scene(self):
		with patch('joymedia.services.consistency.repair._project_asset_path') as access, patch.object(
			frappe.db, 'get_value', side_effect=['OTHER-SCENE', 'THIS-SCENE']
		), patch.object(frappe, 'throw', side_effect=ValueError):
			with self.assertRaises(ValueError):
				_validate_source_take('PROJECT', 'SELECTED', 'CANDIDATE')
		access.assert_called_once_with('PROJECT', 'CANDIDATE')

	def test_unselected_same_scene_source_is_checked_without_changing_selection(self):
		with patch('joymedia.services.consistency.repair._project_asset_path') as access, patch.object(
			frappe.db, 'get_value', return_value='THIS-SCENE'
		), patch.object(frappe.db, 'set_value') as write:
			_validate_source_take('PROJECT', 'SELECTED', 'CANDIDATE')
		access.assert_called_once_with('PROJECT', 'CANDIDATE')
		write.assert_not_called()

	def test_candidate_only_request_is_frozen_without_selecting_a_take(self):
		project = Mock(name='project')
		project.name = 'OWN'
		with patch.object(frappe, 'get_doc', side_effect=[project, frappe._dict(
			media_project='OWN', selected_output_asset_version='TAKE',
		)]), patch('joymedia.services.consistency.repair._project_asset_path'), \
			patch.object(frappe, 'enqueue') as enqueue, patch.object(frappe.db, 'commit'):
			queue_source_art_repair('OWN', 'SHOT', 'TAKE', [
				{'artwork':'A', 'source_quad':[], 'target_quad':[], 'blend_mode':'seamless'}
			], select_result='false')
			self.assertIs(enqueue.call_args.kwargs['select_result'], False)

	def test_cross_project_asset_is_not_authorized_by_knowing_its_identifier(self):
		project = frappe._dict(name="OWN", selected_media=[])
		with (
			patch.object(
				frappe,
				"get_doc",
				side_effect=[frappe._dict(media_asset="A"), frappe._dict(media_project="OTHER")],
			),
			patch.object(frappe, "throw", side_effect=PermissionError),
		):
			with self.assertRaises(PermissionError):
				_require_asset_version_access(project, "FOREIGN")

	def test_library_assets_must_be_explicitly_selected(self):
		project = frappe._dict(name="OWN", selected_media=[])
		with (
			patch.object(
				frappe,
				"get_doc",
				side_effect=[frappe._dict(media_asset="A"), frappe._dict(media_project=None)],
			),
			patch.object(frappe, "throw", side_effect=PermissionError),
		):
			with self.assertRaises(PermissionError):
				_require_asset_version_access(project, "LIBRARY")

	def test_repair_cannot_select_a_stale_or_foreign_scene(self):
		project = Mock()
		project.name = "OWN"
		for owner, take in [("OTHER", "TAKE"), ("OWN", "NEWER")]:
			with (
				patch.object(
					frappe,
					"get_doc",
					side_effect=[
						project,
						frappe._dict(media_project=owner, selected_output_asset_version=take),
					],
				),
				patch.object(frappe, "throw", side_effect=ValueError),
			):
				with self.assertRaises(ValueError):
					queue_source_art_repair("OWN", "SHOT", "TAKE", [])
		self.assertEqual(project._require_write_access.call_count, 2)

	def test_raw_paths_and_unknown_controls_are_rejected(self):
		project = Mock()
		project.name = "OWN"
		with (
			patch.object(
				frappe,
				"get_doc",
				side_effect=[
					project,
					frappe._dict(media_project="OWN", selected_output_asset_version="TAKE"),
				],
			),
			patch.object(frappe, "throw", side_effect=ValueError),
		):
			with self.assertRaises(ValueError):
				queue_source_art_repair(
					"OWN",
					"SHOT",
					"TAKE",
					[{"artwork": "A", "source_quad": [], "target_quad": [], "output_path": "/etc/host"}],
				)
