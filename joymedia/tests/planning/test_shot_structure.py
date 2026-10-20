import copy
import json
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from joymedia.services.planning.camera import camera_plan
from joymedia.services.planning.plan_parsing import _normalized_motion_plan
from joymedia.services.planning.production_case import read_case
from joymedia.services.planning.shot_structure import shot_structure


class TestShotStructure(TestCase):
	def test_approval_does_not_fill_an_intentionally_unassigned_structured_shot(self):
		from joymedia.api.storyboard import _bind_unassigned_project_references

		scene = self.scene()
		scene.generation_inputs = []
		scene.append, scene.save = Mock(), Mock()
		project = frappe._dict(
			name="P", selected_media=[frappe._dict(asset_version="PACK", reference_role="Product")]
		)
		with (
			patch.object(frappe.db, "get_value", side_effect=["ASSET", "Image"]),
			patch.object(frappe, "get_all", return_value=["S"]),
			patch.object(frappe, "get_doc", return_value=scene),
		):
			_bind_unassigned_project_references(project)
		scene.append.assert_not_called()
		scene.save.assert_not_called()

	def test_unplanned_framing_does_not_cycle_with_scene_number(self):
		from joymedia.services.planning.camera import camera_plan

		for number in range(1, 9):
			self.assertEqual(
				"the supplied opening composition",
				camera_plan(frappe._dict(shot_number=number), {})["framing"],
			)

	def test_camera_grammar_uses_purpose_instead_of_alternating_shot_numbers(self):
		from joymedia.services.planning.camera import infer_cinematic_intent

		structure = self.scene().motion_plan_json["shot_structure"]
		self.assertEqual("locked", infer_cinematic_intent(structure, opening=True)["behavior"])
		structure.update(stage="establish", framing="wide")
		self.assertEqual("hook", infer_cinematic_intent(structure, opening=True)["purpose"])
		structure.update(stage="feel", framing="medium")
		self.assertEqual("push_in", infer_cinematic_intent(structure)["behavior"])
		structure.update(subject_motion="locomotion")
		self.assertEqual("follow", infer_cinematic_intent(structure)["purpose"])

	def test_cinematic_hook_moves_only_with_safe_margins_and_broad_coverage(self):
		scene = self.scene()
		scene.motion_plan_json["shot_structure"].update(stage="establish", framing="wide")
		scene.motion_plan_json["camera_intent"] = {
			"behavior": "push_in",
			"allow_reframe": False,
			"purpose": "hook",
			"energy": "measured",
		}
		safe = {"status": "assessed", "complete": True, "bounds": [0.15, 0.15, 0.85, 0.85]}
		result = camera_plan(scene, {}, framing_safety=safe)
		self.assertEqual("push_in", result["behavior"])
		self.assertIn("at most 6 percent", result["direction"])
		self.assertIn("complete stop", result["direction"])
		self.assertEqual("locked", camera_plan(scene, {})["behavior"])
		scene.motion_plan_json["shot_structure"].update(stage="extract", framing="close_up")
		self.assertEqual("locked", camera_plan(scene, {}, framing_safety=safe)["behavior"])

	def test_spatial_reveal_needs_both_reviewed_endpoints(self):
		scene = self.scene()
		scene.motion_plan_json["shot_structure"].update(
			stage="present", subject_motion="stationary", framing="wide"
		)
		scene.motion_plan_json["camera_intent"] = {
			"behavior": "pull_back",
			"allow_reframe": True,
			"purpose": "reveal",
			"energy": "measured",
		}
		self.assertEqual("locked", camera_plan(scene, {})["behavior"])
		scene.references = [{"reference_role": "first_frame"}, {"reference_role": "last_frame"}]
		self.assertEqual("pull_back", camera_plan(scene, {})["behavior"])

	def test_explicit_empty_cast_does_not_add_a_fallback_actor(self):
		from joymedia.services.intake.references import find_reference
		from joymedia.services.planning.workbook import _scenes

		scene = _scenes(
			[["Scene", "Action", "Cast"], ["Detail", "Four layers flex.", "x"]],
			0,
			{0: "beat_name", 1: "action", 2: "cast"},
		)[0]
		self.assertTrue(scene["cast_declared"])
		self.assertEqual([], scene["cast"])
		canonical = {"key": "actor", "label": "Main character", "aliases": ["Main character holding heart"]}
		self.assertIs(canonical, find_reference("Main character holding heart", [canonical]))

	def scene(self):
		contract = {
			"version": 1,
			"entities": [
				{"id": "person", "label": "the approved person"},
				{"id": "item", "label": "the approved ceramic cup"},
				{"id": "bag", "label": "the approved soft bag"},
			],
			"relations": [],
			"events": [],
		}
		structure = {
			"stage": "extract",
			"framing": "close_up",
			"angle": "oblique",
			"subject_motion": "manipulation",
			"keep_visible": ["person", "item", "bag"],
		}
		return frappe._dict(
			name="shot",
			shot_number=1,
			duration_seconds=4,
			generation_prompt="The hand retrieves the same cup.\n\nAudio: sound effects: fabric rustle.",
			image_prompt="The cup is inside the bag, hand poised outside.",
			start_state="The hand is outside the opening.",
			end_state="The cup rests on its support.",
			references=[],
			continuity_mode="New Scene",
			motion_plan_json={
				"actions": [
					{"start": 0, "end": 2, "action": "Grip the item."},
					{"start": 2, "end": 4, "action": "Extract the same item."},
				],
				"scene_contract": contract,
				"shot_structure": structure,
			},
		)

	def test_manipulation_locks_camera_even_when_a_push_is_requested(self):
		scene = self.scene()
		scene.motion_plan_json["camera_intent"] = {"behavior": "push_in", "allow_reframe": True}
		result = camera_plan(scene, {})
		self.assertEqual(result["behavior"], "locked")
		self.assertEqual(result["framing"], "oblique close-up")
		self.assertIn("the approved ceramic cup", result["direction"])
		self.assertNotIn("T-shirt", result["direction"])

	def test_locomotion_tracks_without_overriding_framing_or_preservation(self):
		scene = self.scene()
		scene.motion_plan_json["shot_structure"].update(subject_motion="locomotion", framing="medium")
		result = camera_plan(scene, {}, is_final=True)
		self.assertEqual("tracking", result["behavior"])
		self.assertEqual("oblique medium", result["framing"])
		self.assertIn("opening framing", result["direction"])
		self.assertIn("continuous depth-dependent parallax", result["direction"])
		self.assertIn("Never slide, loop, reset", result["direction"])
		self.assertNotIn("full-body", result["direction"])
		scene.motion_plan_json["camera_motion"] = "locked"
		self.assertEqual("locked", camera_plan(scene, {})["behavior"])

	def test_unknown_entity_and_arbitrary_camera_fields_are_rejected(self):
		scene = self.scene()
		structure = copy.deepcopy(scene.motion_plan_json["shot_structure"])
		structure["keep_visible"].append("invented_lid")
		with self.assertRaises(ValueError):
			shot_structure(structure, scene.motion_plan_json["scene_contract"])
		structure.pop("keep_visible")
		structure["model"] = "some-model"
		with self.assertRaises(ValueError):
			shot_structure(structure)

	def test_plan_normalizer_preserves_structure_and_event_dependencies(self):
		scene = self.scene()
		scene.motion_plan_json["scene_contract"]["events"] = [
			{"id": "grip", "start": 0, "end": 2, "description": "Grip the item.", "after": []},
			{
				"id": "clear",
				"start": 2,
				"end": 4,
				"description": "Clear the actual opening.",
				"after": ["grip"],
			},
		]
		result = _normalized_motion_plan(scene.motion_plan_json, 4, "Retrieve the item.")
		self.assertEqual(result["shot_structure"], scene.motion_plan_json["shot_structure"])
		self.assertEqual(result["scene_contract"]["events"][1]["after"], ["grip"])

	def test_shared_camera_is_serialized_for_h3_and_other_video_workflows(self):
		from joymedia.services.planning.prompts import compile_segment_prompt_from_snapshot

		scene = self.scene()
		project = frappe._dict(soundtrack_mode="Sound effects only")
		workflows = [
			{"workflow_json": {"node": {"class_type": "MiniMaxH3TextToVideo"}}},
			{"workflow_json": {"node": {"class_type": "KSampler"}}},
		]
		with patch("joymedia.services.planning.framing.inspect_framing", return_value=None):
			for workflow in workflows:
				text = compile_segment_prompt_from_snapshot(scene, project, 1, 1, workflow=workflow)
				self.assertIn("No pan, tilt, orbit, zoom or rack focus", text)
				self.assertIn("Extract the same item.", text)
				self.assertIn("the approved ceramic cup", text)
				if workflow is workflows[1]:
					self.assertNotIn("integrated_multimodal_description:", text)

	def test_new_keyframe_gets_angle_without_performing_later_actions(self):
		from joymedia.services.planning.prompts import compile_prompt_for_documents

		text = compile_prompt_for_documents(self.scene(), {}, prompt_source="image")
		self.assertIn("New keyframe composition: oblique close-up", text)
		self.assertNotIn("Extract the same item.", text)

	def test_person_draw_path_keeps_detail_framing_and_product_presence(self):
		from joymedia.services.planning.prompts import compile_prompt_for_documents

		scene = self.scene()
		scene.character_mode = "Draw in scene"
		scene.setting_prompt = "A neutral work surface."
		scene.references = [{"reference_role": "Person"}, {"reference_role": "Product"}]
		text = compile_prompt_for_documents(scene, {}, prompt_source="image")
		self.assertIn("New keyframe composition: oblique close-up", text)
		self.assertIn("Show the product itself", text)
		self.assertNotIn("seen in a medium or wide shot", text)
		self.assertNotIn("Extract the same item.", text)

	def test_product_detail_does_not_request_a_full_object_reveal(self):
		scene = self.scene()
		scene.references = [{"reference_role": "Product"}]
		direction = camera_plan(scene, {})["direction"]
		self.assertIn("a detail view stays a detail", direction)
		self.assertIn("Authored object movement and natural occlusion changes remain allowed", direction)
		self.assertNotIn("fully visible", direction)

	def test_continuation_uses_only_its_action_window(self):
		from joymedia.services.planning.prompts import compile_segment_prompt_from_snapshot

		scene = self.scene()
		with patch("joymedia.services.planning.framing.inspect_framing", return_value=None):
			text = compile_segment_prompt_from_snapshot(
				scene, {}, 2, 2, segment_start_frame=48, segment_effective_frames=48, fps=24
			)
		self.assertIn("Extract the same item.", text)
		self.assertNotIn("Grip the item.", text)

	def test_case_rejects_engine_settings_and_preserves_reference_evidence(self):
		scene = self.scene()
		case = read_case(
			{
				"version": 3,
				"reference_requirements": {"hands": {"role": "Person"}},
				"shots": [
					{
						"shot_number": 1,
						"name": "Retrieve the cup",
						"duration_seconds": 4,
						"continuity": "New Scene",
						"references": ["hands"],
						"action": scene.generation_prompt,
						"opening": scene.start_state,
						"ending": scene.end_state,
						"image_prompt": scene.image_prompt,
						"sound": "Fabric rustle.",
						"motion_plan": scene.motion_plan_json,
						"readiness": {"action_reference_is_product_reference": False},
					}
				],
			}
		)
		self.assertEqual(case["shots"][0]["motion_plan"]["shot_structure"]["stage"], "extract")
		self.assertFalse(case["shots"][0]["readiness"]["action_reference_is_product_reference"])
		case["model"] = "fixed-engine"
		with self.assertRaises(ValueError):
			read_case(case)

	def test_required_reference_gate_matches_normalized_roles_and_exact_assets(self):
		from joymedia.services.planning.shot_structure import require_scene_references

		snapshot = {
			"references": [
				{"reference_key": "hands", "reference_role": "Person", "asset_version": "approved"}
			]
		}
		scene = {
			"motion_plan_json": {"required_references": [{"key": "hands", "role": "Person"}]},
			"references": [{"reference_role": "person", "asset_version": "approved"}],
		}
		require_scene_references(snapshot, scene)
		scene["references"][0]["asset_version"] = "substituted"
		with self.assertRaises(ValueError):
			require_scene_references(snapshot, scene)
		scene["motion_plan_json"]["required_references"].append({"key": "tag", "role": "General"})
		with self.assertRaises(ValueError):
			require_scene_references(snapshot, scene)

	def test_explicit_neutral_prop_role_is_not_inferred_as_product(self):
		from joymedia.joymedia.doctype.project_reference.project_reference import assign_reference_role

		ref = frappe._dict(reference_role="General", label="packaging", reference_key="packaging")
		assign_reference_role(ref)
		self.assertEqual(ref.reference_role, "General")
		ref.reference_role = ""
		assign_reference_role(ref)
		self.assertEqual(ref.reference_role, "Product")

	def test_preparation_failure_without_tasks_starts_a_fresh_ui_run(self):
		from joymedia.joymedia.doctype.media_project import media_project as m

		for tasks_exist in [False, True]:
			project = frappe._dict(
				name="project",
				workflow="workflow",
				storyboard_approval_status="Approved",
				_require_write_access=Mock(),
				_require_video_idea=Mock(),
				generate_video=Mock(return_value={"run": "fresh"}),
				retry_failed_jobs=Mock(return_value={"run": "retry"}),
			)
			with (
				patch("joymedia.services.planning.signature.assert_plan_matches_approval"),
				patch.object(m, "build_project_snapshot", return_value=({}, "same")),
				patch.object(
					frappe.db, "get_value", side_effect=[frappe._dict(name="failed", status="Failed"), "same"]
				),
				patch.object(
					frappe.db,
					"exists",
					side_effect=lambda doctype, filters: tasks_exist
					if doctype == "Generation Task"
					else True,
				),
			):
				result = m.MediaProject.generate_end_to_end(project)
			self.assertEqual(result["run"], "retry" if tasks_exist else "fresh")

	def test_phase_check_does_not_require_a_grip_after_release(self):
		from joymedia.services.scene.contract import instruction, read_contract
		from joymedia.services.scene.evidence import SequenceCheck, batches, claims_for, evaluate

		scene = self.scene()
		contract = scene.motion_plan_json["scene_contract"]
		contract["events"] = [
			{"id": "carry", "start": 0, "end": 2, "description": "Carry the item.", "after": []},
			{
				"id": "release",
				"start": 2,
				"end": 4,
				"description": "Release the supported item.",
				"after": ["carry"],
			},
		]
		contract["checks"] = [
			{
				"id": "grip",
				"scope": "event",
				"event": "carry",
				"claim": "The hand maintains contact with the item while carrying it.",
			}
		]
		claims = claims_for(scene.motion_plan_json, 4, "Carry then release.")
		claim = next(c for c in claims if c["id"] == "check.grip")
		check = SequenceCheck([b"image"] * 5, [{"time": i} for i in range(5)], [claim], {})
		windows = list(batches(check))
		self.assertEqual([w[0] for w in windows], [(0, 1, 2)])
		answer = {
			"observations": [
				{"id": "check.grip", "verdict": "violated", "frames": [4], "reason": "Hand released."}
			]
		}
		self.assertEqual(evaluate(check, answer)["results"][0]["verdict"], "uncertain")
		self.assertNotIn("maintains contact", instruction(scene.motion_plan_json, 4, start=2, end=4))
		contract["checks"][0]["event"] = "invented"
		with self.assertRaises(ValueError):
			read_contract(scene.motion_plan_json, 4)

	def test_phase_without_sampled_evidence_cannot_be_checked_elsewhere(self):
		from joymedia.services.scene.evidence import SequenceCheck, batches

		check = SequenceCheck(
			[b"frame"],
			[{"time": 3}],
			[
				{
					"id": "check.grip",
					"dimension": "staging",
					"mode": "invariant",
					"claim": "Grip.",
					"window": [0, 1],
					"strict_window": True,
				}
			],
			{},
		)
		with self.assertRaises(ValueError):
			list(batches(check))
