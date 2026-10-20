from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.consistency.retention import policy, require_coverage, required_sources
from scripts.identity_screening_qualification import verify


class TestReferenceRetention(TestCase):
	def test_product_rules_are_case_and_provider_independent(self):
		for source in ["tissue-photo", "ceramic-vase", "cosmetic-bottle"]:
			refs = [{"reference_role": "Product", "asset_version": source}]
			self.assertEqual([source], required_sources(refs + refs))
			with self.assertRaises(ValueError):
				require_coverage({"reference_retention": {"version": 1}, "references": refs}, None)
			require_coverage(
				{"reference_retention": {"version": 1}, "references": refs},
				{"items": [{"source_asset_version": source}]},
			)

	def test_a_different_source_cannot_supply_coverage(self):
		with self.assertRaises(ValueError):
			require_coverage(
				{
					"reference_retention": {"version": 1},
					"references": [{"reference_role": "product", "asset_version": "CURRENT"}],
				},
				{"items": [{"source_asset_version": "OLD"}]},
			)

	def test_legacy_jobs_keep_their_frozen_behavior(self):
		require_coverage({"references": [{"reference_role": "product", "asset_version": "SOURCE"}]}, None)

	def test_bad_recipe_is_rejected_before_any_provider_call(self):
		with patch.dict(
			frappe.conf, {"joymedia_reference_retention": {"enabled": True, "recipe_sha256": "latest"}}
		):
			with self.assertRaises(ValueError):
				policy()

	def test_uncertain_identity_cannot_promote_a_take(self):
		import io

		from PIL import Image

		b = io.BytesIO()
		Image.new("RGB", (32, 32), "white").save(b, "PNG")
		picture = b.getvalue()
		endpoint = frappe._dict(model="pinned-judge", base_url="http://judge", timeout=2)
		for verdict in ["drift", "uncertain", "invalid"]:
			response = Mock(ok=True)
			response.json.return_value = {
				"choices": [
					{
						"message": {
							"content": frappe.as_json({"verdict": verdict, "reason": "Changed eye type"})
						}
					}
				]
			}
			with (
				patch("scripts.identity_screening_qualification.endpoint", return_value=endpoint),
				patch.object(frappe.db, "get_value", return_value="image.png"),
				patch.object(frappe, "get_doc", return_value=Mock(get_content=lambda: picture)),
				patch("scripts.identity_screening_qualification.requests.post", return_value=response),
			):
				with self.assertRaises(ValueError):
					verify(
						[{"reference_role": "Character", "asset_version": "SOURCE"}],
						[picture],
						{"screen_identity": True, "identity_model": "pinned-judge"},
					)

	def test_no_actor_does_not_invent_an_identity_review(self):
		self.assertIsNone(
			verify([{"reference_role": "Product", "asset_version": "SOURCE"}], [], {"screen_identity": True})
		)

	def test_deforming_identities_remain_candidates_even_if_a_judge_says_passed(self):
		from joymedia.services.consistency.retention import needs_identity_review

		for role in ["Character", "Person"]:
			row = {
				"reference_retention": {"version": 1},
				"references": [{"reference_role": role, "asset_version": "ORIGINAL"}],
				"duration_seconds": 4,
			}
			self.assertTrue(needs_identity_review(row))
			self.assertFalse(needs_identity_review({**row, "closing_hold_seconds": 4}))
			self.assertTrue(needs_identity_review({**row, "closing_hold_seconds": 2}))

	def test_identity_candidate_does_not_replace_the_selected_take_or_timeline(self):
		from joymedia.services.generation import orchestrator

		run = frappe._dict(
			name="RUN",
			execution_scope_json="{}",
			project_snapshot_json=frappe.as_json(
				{
					"shots": [
						{
							"shot": "SHOT",
							"reference_retention": {"version": 1},
							"references": [{"reference_role": "Character", "asset_version": "ORIGINAL"}],
						}
					]
				}
			),
		)
		with (
			patch.object(orchestrator, "_is_keyframe_run", return_value=False),
			patch.object(frappe, "get_all", side_effect=[["SHOT"], [frappe._dict(status="Completed")]]),
			patch.object(orchestrator, "compose_shot_segments", return_value="CANDIDATE") as compose,
			patch("joymedia.services.editing.timeline.update_timeline_source_for_shot") as update,
		):
			orchestrator._finalize_completed_shots(run)
		compose.assert_called_once_with("RUN", "SHOT", select_output=False)
		update.assert_not_called()

	def test_a_cache_cannot_move_artwork_or_rewrite_its_source_evidence(self):
		import io

		from PIL import Image

		from joymedia.services.consistency.retention import validate_prepared

		def png(image):
			b = io.BytesIO()
			image.save(b, "PNG")
			return b.getvalue()

		canvas = Image.new("RGB", (32, 32), "white")
		canvas.paste((100, 20, 40), (8, 8, 24, 24))
		patch_bytes = png(Image.new("RGBA", (16, 16), (100, 20, 40, 255)))
		report = {
			"source_sha256": "SOURCE",
			"recipe_sha256": "RECIPE",
			"source_rgb_unchanged": True,
			"box": [8, 8, 16, 16],
		}
		frozen = {"recipe_sha256": "RECIPE"}
		validate_prepared(png(canvas), patch_bytes, report, "SOURCE", frozen)
		for changed in [
			{"box": [0, 0, 16, 16]},
			{"source_sha256": "OTHER"},
			{"recipe_sha256": "LATEST"},
			{"box": [8, 8, 17, 16]},
		]:
			with self.assertRaises(ValueError):
				validate_prepared(png(canvas), patch_bytes, {**report, **changed}, "SOURCE", frozen)

	def test_first_multi_segment_candidate_can_complete_without_becoming_selected(self):
		from joymedia.services.generation import run_state

		run = frappe._dict(
			name="RUN", execution_scope_json='{"candidate_only":true}', project_snapshot_json="{}"
		)
		jobs = [
			frappe._dict(name="LAST", shot="SHOT", workflow="VIDEO", segment_index=1),
			frappe._dict(name="FIRST", shot="SHOT", workflow="VIDEO", segment_index=0),
		]
		with (
			patch.object(run_state, "_is_keyframe_run", return_value=False),
			patch.object(frappe, "get_doc", return_value=run),
			patch.object(frappe, "get_all", return_value=jobs),
			patch.object(frappe.db, "get_value", side_effect=["Video", "FINAL-ATTEMPT", "Video"]),
			patch.object(frappe.db, "exists", return_value=True) as exists,
		):
			self.assertTrue(run_state._run_outputs_are_selected("RUN"))
		exists.assert_called_once_with(
			"Asset Version", {"source_generation_attempt": "FINAL-ATTEMPT", "source": "Composed"}
		)

	def test_review_selection_rejects_a_stale_history_tab(self):
		from joymedia.services.generation import takes

		with (
			patch.object(
				takes, "_project_shot", return_value=(frappe._dict(name="PROJECT"), frappe._dict(name="SHOT"))
			),
			patch.object(frappe.db, "sql", return_value=[["NEWER"]]),
			patch.object(frappe, "throw", side_effect=ValueError),
			patch.object(takes, "select_scene_take") as choose,
		):
			with self.assertRaises(ValueError):
				takes.use_reviewed_take("PROJECT", "SHOT", "CANDIDATE", "OLDER")
		choose.assert_not_called()

	def test_source_hold_requires_explicit_static_facts_and_never_drops_an_action(self):
		from joymedia.services.consistency.retention import is_static_presentation

		plan = {
			"camera_motion": "locked",
			"scene_contract": {
				"version": 1,
				"entities": [{"id": "item", "label": "the referenced object"}],
				"properties": [{"entity": "item", "name": "motion", "value": "stationary"}],
				"events": [],
			},
		}
		base = {
			"references": [{"reference_role": "Product", "asset_version": "ANY-SOURCE"}],
			"motion_plan_json": plan,
			"duration_seconds": 4,
		}
		self.assertTrue(is_static_presentation(base))
		self.assertFalse(
			is_static_presentation(
				{
					**base,
					"references": base["references"]
					+ [{"reference_role": "Character", "asset_version": "ACTOR"}],
				}
			)
		)
		self.assertFalse(
			is_static_presentation({**base, "motion_plan_json": {**plan, "camera_motion": "moving"}})
		)
		self.assertFalse(
			is_static_presentation(
				{
					**base,
					"motion_plan_json": {
						**plan,
						"scene_contract": {
							**plan["scene_contract"],
							"events": [{"id": "open", "description": "Open the lid", "start": 0, "end": 2}],
						},
					},
				}
			)
		)
		self.assertFalse(is_static_presentation({**base, "motion_plan_json": {"camera_motion": "locked"}}))

	def test_silent_video_replacement_does_not_read_the_deleted_linked_audio(self):
		from joymedia.services.editing import timeline

		project = Mock()
		project.name = "PROJECT"
		shot = frappe._dict(name="SHOT", media_project="PROJECT", selected_output_asset_version="SILENT")
		clip = Mock(track_type="Video", source_out_frame=120, source_in_frame=0, initial_source_out_frame=120)

		def clips(dt, filters, **kwargs):
			return ["VIDEO"] if filters.get("track_type") == "Video" else ["VIDEO", "DELETED-AUDIO"]

		with (
			patch.object(frappe, "get_doc", side_effect=[project, shot, clip]),
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_all", side_effect=clips),
			patch.object(timeline, "_require_project_write"),
			patch.object(timeline, "_project_fps", return_value=24),
			patch.object(timeline, "_source_max_frames", return_value=120),
			patch.object(timeline, "_sync_linked_audio_clip"),
			patch.object(timeline, "_normalize_transitions"),
			patch.object(timeline, "_invalidate_project_output"),
			patch.object(timeline, "_timeline_clip_rows", return_value=[]),
			patch.object(timeline, "_serialize_timeline", return_value={}),
			patch.object(frappe.db, "commit"),
		):
			timeline.update_timeline_source_for_shot("PROJECT", "SHOT")


class TestScreenArtworkCoverage(__import__("unittest").TestCase):
	def test_screen_typography_cannot_substitute_for_a_physical_product(self):
		from joymedia.services.consistency.retention import require_coverage

		with self.assertRaises(ValueError):
			require_coverage(
				{
					"reference_retention": True,
					"references": [{"reference_role": "Product", "asset_version": "P"}],
				},
				{
					"items": [
						{"source_asset_version": "P", "coordinate_space": "screen", "kind": "typography"}
					]
				},
			)


class TestRetentionDiagnostics(__import__("unittest").TestCase):
	def test_worker_cause_survives_warning_and_traceback_truncation(self):
		from joymedia.services.consistency.retention import RetentionRejected, rejection_reason
		from joymedia.services.generation.failures import technical_message

		reason = "Original source cannot fit the detected footprint."
		diagnostic = (
			"FutureWarning: irrelevant warning\n" * 40
			+ 'Traceback (most recent call last):\n  File "worker.py", line 115\nValueError: '
			+ reason
			+ "\n"
		)
		failure = RetentionRejected(
			"Reference preparation was rejected. No unprotected frame was accepted. "
			+ rejection_reason(diagnostic)
		)
		self.assertIn(reason, technical_message(failure))
		self.assertNotIn("FutureWarning", str(failure))

	def test_occlusion_rejection_remains_an_explicit_failure(self):
		from joymedia.services.consistency.retention import RetentionRejected, rejection_reason

		reason = "Product overlaps a limb; an occlusion-aware workflow is required."
		self.assertEqual(reason, rejection_reason("ValueError: " + reason))
		self.assertIsInstance(RetentionRejected(reason), ValueError)
