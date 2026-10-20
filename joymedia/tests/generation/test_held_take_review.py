"""Retained uncertainty is reviewable footage, never revived automatic approval."""

import copy
import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.consistency.repair import held_take_review_candidate
from joymedia.services.generation import takes


def findings():
	rows = [
		{"id": "authored_action", "dimension": "action", "verdict": "supported"},
		{"id": "cast_inventory", "dimension": "cast", "verdict": "supported"},
		{"id": "reference.actor", "dimension": "identity", "verdict": "supported"},
		{"id": "continuity", "dimension": "consistency", "verdict": "uncertain"},
		{"id": "physics", "dimension": "physics", "verdict": "uncertain"},
	]
	return {"status": "Needs Review", "results": rows, "required_claim_ids": [r["id"] for r in rows]}


class TestHeldTakeReview(TestCase):
	def test_retaining_uncertainty_never_changes_the_report_or_accepts_other_findings(self):
		report = findings()
		original = copy.deepcopy(report)
		self.assertTrue(held_take_review_candidate(report))
		self.assertEqual(report, original)
		for index, verdict in [(0, "uncertain"), (1, "uncertain"), (2, "uncertain"), (3, "violated")]:
			bad = copy.deepcopy(report)
			bad["results"][index]["verdict"] = verdict
			self.assertFalse(held_take_review_candidate(bad))
		bad = copy.deepcopy(report)
		bad["results"].pop()
		self.assertFalse(held_take_review_candidate(bad))

	def test_stale_selection_stops_before_reading_or_creating_a_candidate(self):
		with (
			patch.object(
				takes,
				"_project_shot",
				return_value=(Mock(), SimpleNamespace(selected_output_asset_version="NEW")),
			),
			patch.object(takes, "_ensure_scene_free"),
			patch.object(frappe, "throw", side_effect=ValueError),
			patch.object(frappe, "get_doc") as get,
		):
			with self.assertRaises(ValueError):
				takes.retain_held_take_for_review("P", "S", "A", "OLD", "hash", "Inspect the native frames")
			get.assert_not_called()

	def test_exact_held_bytes_are_retained_unselected_and_failed_execution_stays_failed(self):
		from joymedia.services.editing import composer as c

		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "native.mp4"
			path.write_bytes(b"native immutable bytes")
			source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
			project = SimpleNamespace(name="P")
			shot = Mock(
				selected_output_asset_version="OLD",
				duration_seconds=2,
				storyboard_beat="beat",
				source_timing="time",
			)
			shot.name = "S"
			shot.as_dict.return_value = {}
			shot.generation_inputs = []
			attempt = SimpleNamespace(name="A", generation_task="T", status="Failed")
			task = SimpleNamespace(
				name="T", shot="S", status="Failed", generation_run="R", segment_frame_count=48
			)
			run = SimpleNamespace(
				name="R",
				media_project="P",
				status="Failed",
				project_snapshot_json=json.dumps({"shots": [{"shot": "S"}]}),
			)
			artifact = SimpleNamespace(name="G", generation_attempt="A")
			report = findings()
			report.update(
				source_sha256=source_hash,
				snapshot_sha256=hashlib.sha256(run.project_snapshot_json.encode()).hexdigest(),
				artifact="G",
			)
			docs = {
				"Generation Attempt": attempt,
				"Generation Task": task,
				"Generation Run": run,
				"Generation Artifact": artifact,
			}
			with (
				patch.object(takes, "_project_shot", return_value=(project, shot)),
				patch.object(takes, "_ensure_scene_free"),
				patch.object(frappe, "get_doc", side_effect=lambda kind, *args: docs[kind]),
				patch.object(frappe, "get_all", return_value=["T"]),
				patch.object(frappe.db, "commit"),
				patch.object(frappe.utils, "now_datetime", return_value="now"),
				patch("joymedia.services.review.admission.report_for", return_value=report),
				patch("joymedia.services.project.context._sheet_scenes", return_value={}),
				patch("joymedia.services.scene.direction.authored_action", return_value="interaction"),
				patch("joymedia.services.scene.direction.direction_changed", return_value=False),
				patch.object(c, "_get_artifact_path", return_value=path),
				patch.object(
					c, "_get_or_create_shot_output_asset", return_value=SimpleNamespace(name="OUTPUT")
				),
				patch.object(c, "_get_delivery_profile", return_value={"fps": 24}),
				patch.object(c, "_shot_frame_count", return_value=48),
				patch.object(
					c,
					"_normalize_segment",
					side_effect=lambda source, output, *args, **kwargs: output.write_bytes(b"fitted bytes"),
				),
				patch.object(c, "_validate_normalized_video"),
				patch.object(c, "_persist_composed_output", return_value="CANDIDATE") as persist,
			):
				result = takes.retain_held_take_for_review(
					"P", "S", "A", "OLD", source_hash, "Inspect all decoded frames"
				)
			self.assertEqual(
				result, {"asset_version": "CANDIDATE", "selected": False, "status": "Review Required"}
			)
			self.assertEqual((attempt.status, task.status, run.status), ("Failed", "Failed", "Failed"))
			self.assertEqual(shot.selected_output_asset_version, "OLD")
			self.assertFalse(persist.call_args.kwargs["select_output"])
			self.assertFalse(persist.call_args.kwargs["can_select"])
			self.assertEqual(
				persist.call_args.kwargs["review_manifest"]["machine_findings"], report["results"]
			)
