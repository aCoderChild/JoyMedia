import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from joymedia.services.generation import takes as scene_takes
from joymedia.services.generation.orchestrator import _keeps_selected_output
from joymedia.tests.editing.test_timeline import _create_output_version, _create_workflow


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

	@patch("joymedia.services.editing.post_production.resume_post_production_if_approved", return_value={"status": "Awaiting QA"})
	def test_selecting_an_unapproved_take_keeps_selection_and_waits_for_qa(self, resume):
		result = scene_takes.select_scene_take(self.project.name, self.shot.name, 1)

		self.assertEqual(self.takes[0].name, frappe.db.get_value("Shot", self.shot.name, "selected_output_asset_version"))
		self.assertEqual({"shot_name": self.shot.name, "take_count": 2, "take_index": 1, "finishing": "Awaiting QA", "stale_shots": []}, result)
		resume.assert_called_once_with(self.project.name)
		with self.assertRaises(frappe.ValidationError):
			scene_takes.select_scene_take(self.project.name, self.shot.name, 3)

	@patch("joymedia.services.editing.post_production.resume_post_production_if_approved")
	def test_selecting_the_already_selected_take_does_not_request_finishing(self, resume):
		result = scene_takes.select_scene_take(self.project.name, self.shot.name, 2)

		self.assertEqual("Unchanged", result["finishing"])
		resume.assert_not_called()

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

	@patch("joymedia.services.generation.takes.frappe.db.exists", return_value=True)
	@patch("joymedia.services.generation.takes.frappe.db.get_value")
	@patch("joymedia.services.generation.takes.frappe.get_all")
	@patch("joymedia.services.generation.takes.frappe.get_doc")
	def test_continuation_regeneration_uses_selected_predecessor_lineage(
		self, get_doc, get_all, get_value, exists
	):
		continuing = frappe._dict(name="SHOT-00003", shot_number=3, continuity_mode="Continue")
		get_doc.return_value = continuing
		get_all.return_value = [frappe._dict(
			name="SHOT-00002", selected_output_asset_version="ASTV-00002", review_status="Approved"
		)]
		get_value.side_effect = ["ATT-00002", "TASK-00002"]

		result = scene_takes._continuation_source_task(frappe._dict(name="PROJ-00001"), [continuing.name])

		self.assertEqual("TASK-00002", result)
		exists.assert_called_once_with(
			"Generation Artifact",
			{"generation_attempt": "ATT-00002", "artifact_role": "Last Frame", "frappe_file": ["is", "set"]},
		)

	def test_continuation_regeneration_requires_approved_predecessor_output(self):
		with patch("joymedia.services.generation.takes.frappe.get_doc", return_value=frappe._dict(
			name="SHOT-00003", shot_number=3, continuity_mode="Continue"
		)), patch("joymedia.services.generation.takes.frappe.get_all", return_value=[frappe._dict(
			name="SHOT-00002", selected_output_asset_version=None, review_status="Pending Review"
		)]):
			with self.assertRaises(frappe.ValidationError):
				scene_takes._continuation_source_task(frappe._dict(name="PROJ-00001"), ["SHOT-00003"])

	@patch("joymedia.services.project.context._busy_shots")
	def test_only_a_scene_that_is_rendering_is_blocked(self, busy):
		busy.return_value = [self.shot.name]
		with self.assertRaises(frappe.ValidationError):
			scene_takes.select_scene_take(self.project.name, self.shot.name, 1)

		busy.return_value = ["SHOT-OTHER"]
		with patch("joymedia.services.editing.post_production.resume_post_production_if_approved", return_value={"status": "Awaiting QA"}):
			self.assertEqual(1, scene_takes.select_scene_take(self.project.name, self.shot.name, 1)["take_index"])


class TestDownstreamStaleness(FrappeTestCase):
	def test_only_shots_built_on_a_replaced_take_are_flagged(self):
		shot = frappe._dict(name="S1", media_project="P", selected_output_asset_version="AV-new")
		tasks = [
			frappe._dict(name="T2", shot="S2", depends_on_task="T1-old"),
			frappe._dict(name="T3", shot="S3", depends_on_task="T1-new"),
			frappe._dict(name="T4", shot="S4", depends_on_task="T1-old"),
		]
		attempts = {"AV-new": "A-new", "AV2": "A2", "AV4": "A4"}
		attempt_tasks = {"A-new": "T1-new", "A2": "T2", "A4": "T-other"}
		shots = {
			"S2": frappe._dict(selected_output_asset_version="AV2", media_project="P", is_removed=0),
			"S4": frappe._dict(selected_output_asset_version="AV4", media_project="P", is_removed=0),
		}

		def get_value(doctype, name, field=None, as_dict=False):
			if doctype == "Asset Version":
				return attempts[name]
			if doctype == "Generation Attempt":
				return attempt_tasks[name]
			return shots[name]

		def get_all(doctype, **kwargs):
			return ["T1-old", "T1-new"] if kwargs.get("pluck") else tasks

		with patch.object(scene_takes.frappe, "get_all", side_effect=get_all), patch.object(
			scene_takes.frappe.db, "get_value", side_effect=get_value
		), patch.object(scene_takes.frappe.db, "set_value") as set_value:
			stale = scene_takes.mark_stale_downstream_shots(shot)

		# S3 was built on the selected take; S4's output came from a different task lineage.
		self.assertEqual(["S2"], stale)
		set_value.assert_called_once_with("Shot", "S2", "review_status", "Needs Revision", update_modified=False)
