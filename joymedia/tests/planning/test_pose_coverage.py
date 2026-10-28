import io
from unittest import TestCase
from unittest.mock import patch

import frappe
from PIL import Image

from joymedia.services.keyframes.overlay import DRAW, PASTE
from joymedia.services.planning.pose_assets import (
	_accept_pose_view,
	_clean_identity_source,
	_h3_start_view,
	_plan_required_states,
	_pose_view,
	_view_matches,
	_visible_change,
	prepare_script_pose_views,
)
from joymedia.services.planning.pose_coverage import (
	annotate_shots,
	assert_opening_character_references,
	keyframe_character_mode,
	matching_view,
	opening_reference_conflicts,
	pose_requirement,
	required_pose,
)
from joymedia.services.project.reference_lineage import lineage_identity


class TestPoseCoverage(TestCase):
	def test_matching_body_state_does_not_reuse_a_prop_holding_source(self):
		with (
			patch("joymedia.services.planning.pose_assets._observed_pose_matches", return_value=True),
			patch(
				"joymedia.services.review.consistency.ask",
				return_value={"held_object_count": 1, "held_objects": ["heart"]},
			),
		):
			self.assertFalse(_view_matches("/private/files/source.png", "seated on a rug", "front"))

	def test_free_paws_cannot_use_held_prop_source_as_opening_reference(self):
		shot = frappe._dict(
			shot_number=1,
			start_state="The mascot is seated with both paws free.",
			image_prompt="A single mascot beside the table.",
			generation_inputs=[frappe._dict(reference_role="Character", asset_version="source")],
		)
		with patch(
			"frappe.db.get_value",
			return_value=frappe.as_json({"description": "The character is holding a separate toy."}),
		):
			self.assertEqual(["source"], opening_reference_conflicts(shot))
			with self.assertRaisesRegex(ValueError, "prop-free pose"):
				assert_opening_character_references([shot])

	def test_qualified_prop_free_pose_can_open_the_scene(self):
		shot = frappe._dict(
			start_state="The mascot is seated with empty paws.",
			generation_inputs=[frappe._dict(reference_role="Character", asset_version="clean")],
		)
		analysis = {
			"source_asset_version": "source",
			"qualified_pose_and_support": "seated on a rug, paws empty",
			"qualified_pose_view": "front",
			"pose_qualification_version": 2,
		}
		with patch("frappe.db.get_value", return_value=frappe.as_json(analysis)):
			self.assertEqual([], opening_reference_conflicts(shot))

	def test_generated_view_inherits_original_identity_through_asset_lineage(self):
		root = frappe._dict(asset_version="A", identity_key="mascot", reference_role="Character")
		view = frappe._dict(asset_version="B", identity_key="mistaken_variant", reference_role="Character")
		matte = frappe._dict(asset_version="C", identity_key="mistaken_cutout", reference_role="Character")
		project = frappe._dict(selected_media=[root, view, matte])
		analyses = {
			"A": {},
			"B": {"source_asset_version": "A"},
			"C": {"subject_cutout": {"source_asset_version": "B"}},
		}
		with patch(
			"frappe.db.get_value", side_effect=lambda _dt, name, _field: frappe.as_json(analyses[name])
		):
			self.assertEqual("mascot", lineage_identity(project, matte))

	def setUp(self):
		# Planner unit fixtures use synthetic asset versions. Real cutout worker
		# integration is exercised against persisted project media separately.
		cutout = patch("joymedia.services.intake.subject_cutout.sam2_configured", return_value=False)
		cutout.start()
		self.addCleanup(cutout.stop)

	def test_storyboard_keeps_qualified_upright_view_through_later_actions(self):
		seated = frappe._dict(asset_version="seated", identity_key="bear", reference_role="Character")
		upright = frappe._dict(asset_version="upright", identity_key="bear", reference_role="Character")
		project = frappe._dict(
			selected_media=[seated, upright], storyboard_source_json='{"generation_origin":"ai_director"}'
		)
		shots = []
		for action, state in (
			("The bear stands up from the rug.", "The bear is seated on the rug."),
			("The bear walks to the table.", "The bear stands beside the table."),
			("The bear wipes the table.", "The bear stands beside the table."),
			("The bear continues wiping.", "The bear holds a tissue over the table."),
		):
			shot = frappe._dict(
				image_prompt=state,
				start_state=state,
				motion_plan_json=frappe.as_json({"actions": [{"action": action}], "shot_structure": {}}),
				generation_inputs=[frappe._dict(asset_version="seated", reference_role="Character")],
			)
			shot.save = lambda **kwargs: None
			shots.append(shot)
		analysis = {
			"seated": {"pose_and_support": "seated on the rug"},
			"upright": {"pose_and_support": "standing on supported feet"},
		}
		with patch(
			"frappe.db.get_value", side_effect=lambda _dt, name, _field: frappe.as_json(analysis[name])
		):
			annotate_shots(project, shots)
		self.assertEqual(
			["seated", "upright", "upright", "upright"],
			[shot.generation_inputs[0].asset_version for shot in shots],
		)
		self.assertEqual(
			"upright_supported",
			frappe.parse_json(shots[2].motion_plan_json)["pose_requirement"]["opening_pose"],
		)
		self.assertEqual(
			"seated",
			matching_view(
				[seated, upright],
				"upright",
				"seated_supported",
				{"seated": "seated on the rug", "upright": "standing on supported feet"},
			).asset_version,
		)

	def test_storyboard_uses_reviewed_seated_contract_even_if_reanalysis_says_standing(self):
		selected = [
			frappe._dict(asset_version="source", identity_key="bear", reference_role="Character"),
			frappe._dict(asset_version="clean", identity_key="bear", reference_role="Character"),
		]
		project = frappe._dict(
			selected_media=selected, storyboard_source_json='{"generation_origin":"ai_director"}'
		)
		shot = frappe._dict(
			start_state="The bear is seated on the rug with empty paws.",
			image_prompt="The bear is seated on the rug with empty paws.",
			motion_plan_json=frappe.as_json({"actions": [{"action": "The bear notices the spill."}]}),
			generation_inputs=[frappe._dict(asset_version="source", reference_role="Character")],
		)
		shot.save = lambda **kwargs: None
		analysis = {
			"source": {"pose_and_support": "seated holding a heart"},
			"clean": {
				"source_asset_version": "source",
				"pose_qualification_version": 2,
				"pose_and_support": "standing",
				"qualified_pose_and_support": "seated on the floor, paws empty",
			},
		}
		with patch(
			"frappe.db.get_value", side_effect=lambda _dt, name, _field: frappe.as_json(analysis[name])
		):
			annotate_shots(project, [shot])
		self.assertEqual("clean", shot.generation_inputs[0].asset_version)

	def test_held_heart_is_not_a_reusable_mascot_pose(self):
		with (
			patch("joymedia.services.planning.production._ask_planner", return_value={"answer": True}),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True},
					{"held_object_count": 1, "held_objects": ["heart"]},
				],
			),
		):
			self.assertFalse(_accept_pose_view(b"generated image"))
		with (
			patch("joymedia.services.planning.production._ask_planner", return_value={"answer": True}),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True},
					{"held_object_count": 0, "held_objects": []},
					{"fused_lower_body": False},
					{"answer": True},
					{"head_accessories": []},
					{"head_accessories": []},
				],
			),
		):
			self.assertTrue(_accept_pose_view(b"generated image", b"source image"))

	def test_added_head_flower_is_not_a_reusable_mascot_pose(self):
		with (
			patch("joymedia.services.planning.production._ask_planner", return_value={"answer": True}),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True},
					{"held_object_count": 0},
					{"fused_lower_body": False},
					{"answer": True},
					{"head_accessories": []},
					{"head_accessories": ["yellow flower"]},
				],
			),
		):
			self.assertFalse(_accept_pose_view(b"generated image", b"source image", "standing on feet"))

	def test_legacy_pose_qualification_cannot_bypass_current_identity_checks(self):
		from joymedia.services.planning.pose_assets import _qualified_pose_metadata

		legacy = {
			"source_asset_version": "source",
			"qualified_pose_and_support": "standing",
			"qualified_pose_view": "front",
		}
		self.assertIsNone(_qualified_pose_metadata(legacy))
		self.assertEqual(
			"standing", _qualified_pose_metadata({**legacy, "pose_qualification_version": 2})["pose"]
		)

	def test_front_pose_rejects_changed_eye_design(self):
		with (
			patch("joymedia.services.planning.production._ask_planner", return_value={"answer": True}),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True},
					{"held_object_count": 0},
					{"fused_lower_body": False},
					{"answer": True},
					{"head_accessories": []},
					{"head_accessories": []},
					{"eye_shape": "closed_arcs"},
					{"eye_shape": "open_dots"},
				],
			),
		):
			self.assertFalse(
				_accept_pose_view(b"generated image", b"source image", "standing on feet", "front")
			)

	def test_fused_weight_support_is_not_promoted_as_character_reference(self):
		with (
			patch("joymedia.services.planning.production._ask_planner", return_value={"answer": True}),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True},
					{"held_object_count": 0, "held_objects": []},
					{"fused_lower_body": True},
				],
			),
		):
			self.assertFalse(_accept_pose_view(b"generated image"))

	def test_observed_seated_pose_cannot_be_promoted_as_kneeling(self):
		with (
			patch(
				"joymedia.services.review.consistency.ask",
				return_value={
					"pose_description": "seated on rump with feet forward",
					"visible_contact_points": ["rump", "feet"],
					"certainty": "high",
				},
			),
			patch("joymedia.services.planning.production._ask_planner", return_value={"answer": False}),
			patch("joymedia.services.planning.pose_assets._target_pose_matches", return_value=False),
		):
			self.assertFalse(_accept_pose_view(b"seated image", pose_description="kneeling on both knees"))

	def test_target_led_agreement_cannot_override_failed_blind_pose_observation(self):
		with (
			patch("joymedia.services.planning.pose_assets._observed_pose_matches", return_value=False),
			patch(
				"joymedia.services.planning.pose_assets._target_pose_matches", return_value=True
			) as target_led,
		):
			self.assertFalse(_accept_pose_view(b"neutral image", pose_description="one paw extended"))
		target_led.assert_not_called()

	def test_default_pose_renderer_uses_existing_h3_workflow(self):
		with (
			patch("joymedia.services.planning.pose_assets.frappe.conf", {"joymedia_pose_workflow": None}),
			patch(
				"joymedia.services.planning.pose_assets._pose_view_from_h3", return_value=b"qualified"
			) as render,
		):
			self.assertEqual(b"qualified", _pose_view("project", "source", "raised paw", "front"))
			render.assert_called_once_with("project", "source", "raised paw", "front")

	def test_unchanged_frame_cannot_be_a_new_pose(self):
		buffer = io.BytesIO()
		Image.new("RGB", (128, 128), "white").save(buffer, format="PNG")
		self.assertFalse(_visible_change(buffer.getvalue(), buffer.getvalue()))

	def test_h3_bridge_starts_from_accepted_pose_of_same_identity(self):
		clean = frappe._dict(asset_version="clean", identity_key="shera", reference_role="Character")
		upright = frappe._dict(asset_version="upright", identity_key="shera", reference_role="Character")
		other = frappe._dict(asset_version="other", identity_key="other", reference_role="Character")
		project = frappe._dict(selected_media=[clean, upright, other])
		version = frappe._dict(
			file="/upright",
			analysis_status="Ready",
			analysis_json=frappe.as_json(
				{
					"source_asset_version": "clean",
					"pose_qualification_version": 2,
					"pose_and_support": "standing on two feet",
					"view": "front",
				}
			),
		)
		with (
			patch(
				"joymedia.services.planning.pose_assets._clean_identity_source",
				return_value=(clean, "/clean"),
			),
			patch("frappe.db.get_value", return_value=version),
			patch("joymedia.services.planning.pose_assets._retains_body_proportions", return_value=True),
			patch(
				"joymedia.services.planning.production._ask_planner",
				return_value={"asset_version": "upright"},
			),
		):
			choice, url = _h3_start_view(project, clean, "standing side profile", "side")
		self.assertEqual("upright", choice.asset_version)
		self.assertEqual("/upright", url)

	def test_h3_retry_uses_another_accepted_start_view(self):
		clean = frappe._dict(asset_version="clean", identity_key="shera", reference_role="Character")
		upright = frappe._dict(asset_version="upright", identity_key="shera", reference_role="Character")
		project = frappe._dict(selected_media=[clean, upright])
		version = frappe._dict(
			file="/upright",
			analysis_status="Ready",
			analysis_json=frappe.as_json(
				{
					"source_asset_version": "clean",
					"pose_qualification_version": 2,
					"pose_and_support": "standing on two feet",
					"view": "front",
				}
			),
		)
		with (
			patch(
				"joymedia.services.planning.pose_assets._clean_identity_source",
				return_value=(clean, "/clean"),
			),
			patch("frappe.db.get_value", return_value=version),
			patch("joymedia.services.planning.pose_assets._retains_body_proportions", return_value=True),
		):
			choice, url = _h3_start_view(
				project, clean, "standing side profile", "side", exclude_asset_versions={"clean"}
			)
		self.assertEqual("upright", choice.asset_version)
		self.assertEqual("/upright", url)

	def test_pose_source_skips_held_prop_within_same_identity(self):
		rows = [
			frappe._dict(asset_version="heart", identity_key="shera", reference_role="Character"),
			frappe._dict(asset_version="clean", identity_key="shera", reference_role="Character"),
			frappe._dict(asset_version="other", identity_key="other", reference_role="Character"),
		]
		with (
			patch("joymedia.services.planning.pose_assets._retains_body_proportions", return_value=True),
			patch("frappe.db.get_value", side_effect=lambda _dt, name, _field: "/" + name),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"held_object_count": 1},
					{"held_object_count": 0},
				],
			),
		):
			selected, url = _clean_identity_source(frappe._dict(selected_media=rows), rows[0])
		self.assertEqual("clean", selected.asset_version)
		self.assertEqual("/clean", url)

	def test_held_prop_source_can_enter_generation_when_no_clean_view_exists(self):
		row = frappe._dict(asset_version="heart", identity_key="shera", reference_role="Character")
		with (
			patch("frappe.db.get_value", return_value="/heart"),
			patch("joymedia.services.review.consistency.ask", return_value={"held_object_count": 1}),
		):
			selected, url = _clean_identity_source(frappe._dict(selected_media=[row]), row)
		self.assertIs(selected, row)
		self.assertEqual("/heart", url)

	def test_malformed_pose_plan_defers_without_blocking_the_video(self):
		project = frappe._dict(
			name="PRJ-TEST",
			selected_media=[
				frappe._dict(reference_key="bear", identity_key="bear", reference_role="Character")
			],
		)
		script = {"scenes": [{"cast": ["bear"], "action": "The bear waves."}]}
		with (
			patch(
				"joymedia.services.planning.pose_assets._plan_required_states",
				side_effect=ValueError("invalid state"),
			),
			patch("frappe.log_error"),
		):
			result = prepare_script_pose_views(project, script)
		self.assertEqual("deferred", result[0]["status"])
		self.assertEqual("bear", script["scenes"][0]["cast"][0])

	def test_failed_pose_without_new_start_view_does_not_retry_forever(self):
		project = frappe._dict(
			name="PRJ-TEST",
			selected_media=[
				frappe._dict(
					reference_key="bear", identity_key="bear", reference_role="Character", asset_version="A"
				)
			],
		)
		script = {"scenes": [{"cast": ["bear"], "action": "The bear turns sideways."}]}
		state = {
			"scene_index": 0,
			"cast_key": "bear",
			"opening_pose": "standing side profile",
			"view": "side",
		}
		with (
			patch(
				"joymedia.services.planning.pose_assets._plan_required_states", return_value=[state]
			) as planner,
			patch("frappe.db.get_value", return_value="/source"),
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False),
			patch(
				"joymedia.services.planning.pose_assets._pose_view", side_effect=ValueError("unqualified")
			) as render,
			patch("frappe.log_error"),
		):
			result = prepare_script_pose_views(project, script)
		self.assertEqual("deferred", result[0]["status"])
		planner.assert_called_once()
		render.assert_called_once()

	def test_same_failed_pose_is_not_rendered_again_for_next_scene(self):
		project = frappe._dict(
			name="PRJ-TEST",
			selected_media=[
				frappe._dict(
					reference_key="bear", identity_key="bear", reference_role="Character", asset_version="A"
				)
			],
		)
		script = {
			"scenes": [
				{"cast": ["bear"], "action": "The bear reaches."},
				{"cast": ["bear"], "action": "The bear reaches again."},
			]
		}
		states = [
			{
				"scene_index": i,
				"cast_key": "bear",
				"opening_pose": "standing with one paw forward",
				"view": "front",
			}
			for i in (0, 1)
		]
		with (
			patch("joymedia.services.planning.pose_assets._plan_required_states", return_value=states),
			patch(
				"frappe.db.get_value",
				side_effect=lambda _dt, _name, field: "{}" if field == "analysis_json" else "/source",
			),
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False),
			patch(
				"joymedia.services.planning.pose_assets._pose_view", side_effect=ValueError("unqualified")
			) as render,
			patch("frappe.log_error"),
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual(["deferred", "deferred"], [item["status"] for item in prepared])
		render.assert_called_once()

	def test_script_identity_is_replaced_by_a_required_upright_view_before_storyboard(self):
		project = frappe._dict(
			selected_media=[
				frappe._dict(
					reference_key="bear", identity_key="bear", reference_role="Character", asset_version="A"
				),
				frappe._dict(
					reference_key="bear_side",
					identity_key="bear",
					reference_role="Character",
					asset_version="B",
					label="side",
				),
			],
			storyboard_source_json="{}",
		)
		# The Director writes the canonical identity.  The following pose stage,
		# not the screenplay, chooses the side-on view needed by this action.
		script = {
			"scenes": [
				{
					"cast": ["bear"],
					"action": "[0-3s] The bear walks to the pack.",
					"visual_camera": "side profile",
				}
			]
		}
		with (
			patch(
				"joymedia.services.planning.pose_assets._plan_required_states",
				return_value=[
					{
						"scene_index": 0,
						"cast_key": "bear",
						"opening_pose": "standing on both feet",
						"view": "side",
					},
				],
			),
			patch("frappe.db.get_value", side_effect=lambda _dt, name, _field: "/" + name),
			patch("joymedia.services.planning.pose_assets._view_matches", side_effect=[False, True]),
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual(["bear_side"], script["scenes"][0]["cast"])
		self.assertEqual("bear_side", prepared[0]["view"])

	def test_prequalified_director_view_is_reused_without_redrawing(self):
		project = frappe._dict(
			name="PRJ-TEST",
			selected_media=[
				frappe._dict(
					reference_key="bear_seated",
					identity_key="bear",
					reference_role="Character",
					asset_version="A",
				),
				frappe._dict(
					reference_key="bear_standing",
					identity_key="bear",
					reference_role="Character",
					asset_version="B",
				),
			],
		)
		script = {"scenes": [{"cast": ["bear_seated"], "action": "The bear walks toward the pack."}]}
		state = {
			"scene_index": 0,
			"cast_key": "bear_seated",
			"reference_key": "bear_standing",
			"opening_pose": "standing on two supported feet",
			"view": "front",
		}

		def asset_value(_doctype, name, field):
			if field == "analysis_json" and name == "B":
				return frappe.as_json(
					{
						"source_asset_version": "A",
						"pose_qualification_version": 2,
						"pose_and_support": "standing on two supported feet",
					}
				)
			return "/" + name

		with (
			patch("joymedia.services.planning.pose_assets._plan_required_states", return_value=[state]),
			patch("frappe.db.get_value", side_effect=asset_value),
			patch("joymedia.services.planning.pose_assets._view_matches") as observed,
			patch("joymedia.services.planning.pose_assets._pose_view") as redraw,
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual(["bear_standing"], script["scenes"][0]["cast"])
		self.assertEqual("bear_standing", prepared[0]["view"])
		observed.assert_not_called()
		redraw.assert_not_called()

	def test_neutral_qualified_view_cannot_replace_scripted_reaching_paw(self):
		project = frappe._dict(
			name="PRJ-TEST",
			selected_media=[
				frappe._dict(
					reference_key="bear", identity_key="bear", reference_role="Character", asset_version="A"
				),
				frappe._dict(
					reference_key="bear_standing",
					identity_key="bear",
					reference_role="Character",
					asset_version="B",
				),
			],
		)
		script = {"scenes": [{"cast": ["bear"], "action": "The bear reaches toward a pack."}]}
		state = {
			"scene_index": 0,
			"cast_key": "bear",
			"reference_key": "bear_standing",
			"opening_pose": "standing with right paw reaching forward",
			"view": "front",
		}

		def asset_value(_doctype, name, field):
			if field == "analysis_json":
				return (
					frappe.as_json(
						{
							"source_asset_version": "A",
							"pose_qualification_version": 2,
							"qualified_pose_and_support": "standing with both paws relaxed at sides",
							"qualified_pose_view": "front",
						}
					)
					if name == "B"
					else "{}"
				)
			return "/" + name

		with (
			patch("joymedia.services.planning.pose_assets._plan_required_states", return_value=[state]),
			patch("frappe.db.get_value", side_effect=asset_value),
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False),
			patch(
				"joymedia.services.planning.pose_assets._pose_view",
				side_effect=ValueError("no verified reach"),
			) as render,
			patch("frappe.log_error"),
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual("deferred", prepared[0]["status"])
		render.assert_called_once()

	def test_seated_description_with_no_standing_legs_uses_supplied_upright_view(self):
		project = frappe._dict(
			selected_media=[
				frappe._dict(
					reference_key="bear_seated",
					identity_key="bear",
					reference_role="Character",
					asset_version="A",
				),
				frappe._dict(
					reference_key="bear_side",
					identity_key="bear",
					reference_role="Character",
					asset_version="B",
					label="side",
				),
			]
		)
		script = {"scenes": [{"cast": ["bear_seated"], "action": "The bear walks to the pack."}]}
		with (
			patch(
				"joymedia.services.planning.pose_assets._plan_required_states",
				return_value=[
					{
						"scene_index": 0,
						"cast_key": "bear_seated",
						"opening_pose": "standing on both feet",
						"view": "side",
					},
				],
			),
			patch("frappe.db.get_value", side_effect=lambda _dt, name, _field: "/" + name),
			patch("joymedia.services.planning.pose_assets._view_matches", side_effect=[False, True]),
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual("bear_side", prepared[0]["view"])

	def test_planner_requires_every_script_character_without_pose_keyword_rules(self):
		selected = [frappe._dict(reference_key="bear", identity_key="bear", reference_role="Character")]
		script = {
			"scenes": [
				{"cast": ["bear"], "action": "The bear leans over a low surface."},
				{"cast": ["bear"], "action": "The bear turns and reaches with its left paw."},
			]
		}
		states = [
			{
				"scene_index": 0,
				"cast_key": "bear",
				"opening_pose": "kneeling with paws on floor",
				"view": "side",
			},
			{
				"scene_index": 1,
				"cast_key": "bear",
				"opening_pose": "standing with left paw extended",
				"view": "front",
			},
		]
		with patch("joymedia.services.planning.production._ask_planner", return_value={"states": states}):
			self.assertEqual(states, _plan_required_states(script, selected))
		with patch(
			"joymedia.services.planning.production._ask_planner",
			side_effect=[
				{"states": states[:1]},
				{"states": []},
			],
		):
			with self.assertRaisesRegex(ValueError, "every character"):
				_plan_required_states(script, selected)

	def test_prop_contact_pose_is_rewritten_as_prop_free_limb_articulation(self):
		selected = [frappe._dict(reference_key="bear", identity_key="bear", reference_role="Character")]
		script = {
			"scenes": [
				{
					"cast": ["bear"],
					"action": "The bear lifts the product.",
					"start_state": "The bear stands with both paws around the product.",
				}
			]
		}
		planned = {
			"scene_index": 0,
			"cast_key": "bear",
			"reference_key": "bear",
			"opening_pose": "standing on both feet holding a pack at chest height",
			"view": "front",
		}
		with patch(
			"joymedia.services.planning.production._ask_planner",
			side_effect=[
				{"states": [planned]},
				{"pose": "standing on both feet with both paws forward and facing inward at chest height"},
			],
		) as planner:
			state = _plan_required_states(script, selected)[0]
		self.assertIn("both paws forward", state["opening_pose"])
		self.assertEqual(2, planner.call_count)

	def test_planner_completes_only_missing_scene_states(self):
		selected = [frappe._dict(reference_key="bear", identity_key="bear", reference_role="Character")]
		script = {
			"scenes": [
				{"cast": ["bear"], "action": "The bear sits on the floor."},
				{"cast": ["bear"], "action": "The bear stands beside the table."},
			]
		}
		first = {
			"scene_index": 0,
			"cast_key": "bear",
			"reference_key": "bear",
			"opening_pose": "seated on the floor",
			"view": "front",
		}
		second = {
			"scene_index": 1,
			"cast_key": "bear",
			"reference_key": "bear",
			"opening_pose": "standing on two visible feet",
			"view": "front",
		}
		with (
			patch("frappe.db.get_value", return_value="{}"),
			patch(
				"joymedia.services.planning.production._ask_planner",
				side_effect=[
					{"states": [first]},
					{"states": [second]},
				],
			) as planner,
		):
			states = _plan_required_states(script, selected)
		self.assertEqual([0, 1], [state["scene_index"] for state in states])
		self.assertIn('[1, "bear"]', planner.call_args.args[0])

	def test_pose_requirements_are_derived_from_script_actions_not_reference_labels(self):
		selected = [
			frappe._dict(
				reference_key="bear",
				identity_key="shera",
				reference_role="Character",
				asset_version="A",
				label="seated mascot reference photograph",
			)
		]
		script = {
			"scenes": [
				{
					"cast": ["bear"],
					"action": "[0-3s] The mascot walks upright toward the tissue pack.",
					"start_state": "The mascot stands with its right paw extended toward the pack.",
					"image_prompt": "The mascot starts on two supported feet.",
				}
			]
		}
		states = [
			{
				"scene_index": 0,
				"cast_key": "bear",
				"reference_key": "bear",
				"opening_pose": "standing on two supported feet with right paw extended",
				"view": "front",
			}
		]
		with (
			patch("frappe.db.get_value", return_value="{}"),
			patch(
				"joymedia.services.planning.production._ask_planner", return_value={"states": states}
			) as planner,
		):
			self.assertEqual(states, _plan_required_states(script, selected))
		prompt = planner.call_args.args[0]
		self.assertIn("walks upright toward the tissue pack", prompt)
		self.assertIn("right paw extended toward the pack", prompt)
		self.assertIn("A neutral standing pose does not satisfy a scripted reach", prompt)
		self.assertIn("starts on two supported feet", prompt)
		self.assertNotIn("seated mascot reference photograph", prompt)

	def test_planner_normalizes_another_view_of_same_identity_to_scene_cast(self):
		selected = [
			frappe._dict(reference_key="front", identity_key="shera", reference_role="Character"),
			frappe._dict(reference_key="side", identity_key="shera", reference_role="Character"),
		]
		script = {"scenes": [{"cast": ["front"], "action": "Turn sideways."}]}
		with patch(
			"joymedia.services.planning.production._ask_planner",
			return_value={
				"states": [
					{
						"scene_index": 0,
						"cast_key": "side",
						"opening_pose": "standing side profile",
						"view": "side",
					}
				]
			},
		):
			self.assertEqual("front", _plan_required_states(script, selected)[0]["cast_key"])

	def test_planner_collapses_identity_alias_and_exact_cast_key(self):
		selected = [
			frappe._dict(reference_key="mascot_front", identity_key="mascot", reference_role="Character")
		]
		script = {"scenes": [{"cast": ["mascot_front"], "action": "The mascot sits on the floor."}]}
		alias = {
			"scene_index": 0,
			"cast_key": "mascot",
			"reference_key": "mascot_front",
			"opening_pose": "seated on the floor",
			"view": "front",
		}
		exact = {**alias, "cast_key": "mascot_front"}
		with (
			patch("frappe.db.get_value", return_value="{}"),
			patch(
				"joymedia.services.planning.production._ask_planner", return_value={"states": [alias, exact]}
			),
		):
			self.assertEqual([exact], _plan_required_states(script, selected))

	def test_stand_up_opens_seated_but_a_walking_shot_opens_upright(self):
		self.assertEqual("seated_supported", required_pose("The mascot stands up, then walks to the pack."))
		self.assertEqual("upright_supported", required_pose("The mascot walks to the pack."))

	def test_planner_later_standing_pose_is_corrected_to_seated_opening(self):
		selected = [
			frappe._dict(
				reference_key="bear", identity_key="bear", reference_role="Character", asset_version="A"
			)
		]
		script = {
			"scenes": [
				{
					"cast": ["bear"],
					"start_state": "The bear is seated on the rug with both paws free.",
					"action": "The bear stands up, approaches the pack, then lifts it.",
				}
			]
		}
		planner = [
			{
				"states": [
					{
						"scene_index": 0,
						"cast_key": "bear",
						"reference_key": "bear",
						"opening_pose": "standing upright with empty paws",
						"view": "front",
					}
				]
			},
			{"pose": "seated on the rug with both paws free and feet forward"},
		]
		with (
			patch("frappe.db.get_value", return_value="{}"),
			patch("joymedia.services.planning.production._ask_planner", side_effect=planner),
		):
			state = _plan_required_states(script, selected)[0]
		self.assertEqual("bear", state["reference_key"])
		self.assertIn("seated on the rug", state["opening_pose"])

	def test_locomotion_overrides_a_planner_selected_seated_view(self):
		"""A script action wins when a planner response contradicts its support."""
		selected = [
			frappe._dict(
				reference_key="bear", identity_key="shera", reference_role="Character", asset_version="A"
			),
			frappe._dict(
				reference_key="bear_standing",
				identity_key="shera",
				reference_role="Character",
				asset_version="B",
			),
			frappe._dict(
				reference_key="bear_seated",
				identity_key="shera",
				reference_role="Character",
				asset_version="C",
			),
		]
		script = {
			"scenes": [
				{
					"cast": ["bear"],
					"subject_motion": "locomotion",
					"action": "[0-2s] The bear walks to the product.",
				}
			]
		}
		analyses = {
			"B": {
				"source_asset_version": "A",
				"pose_qualification_version": 2,
				"qualified_pose_and_support": "standing upright on two supported feet",
				"qualified_pose_view": "front",
			},
			"C": {
				"source_asset_version": "A",
				"pose_qualification_version": 2,
				"qualified_pose_and_support": "seated on the floor with feet forward",
				"qualified_pose_view": "front",
			},
		}
		with (
			patch(
				"frappe.db.get_value",
				side_effect=lambda _dt, name, _field: frappe.as_json(analyses.get(name, {})),
			),
			patch(
				"joymedia.services.planning.production._ask_planner",
				return_value={
					"states": [
						{
							"scene_index": 0,
							"cast_key": "bear",
							"reference_key": "bear_seated",
							"opening_pose": "seated on the floor",
							"view": "front",
						}
					]
				},
			),
		):
			state = _plan_required_states(script, selected)[0]
		self.assertEqual("bear_standing", state["reference_key"])
		self.assertIn("standing upright", state["opening_pose"])

	def test_distinctive_wave_is_not_replaced_by_first_standing_view(self):
		selected = [
			frappe._dict(
				reference_key="bear", identity_key="shera", reference_role="Character", asset_version="A"
			),
			frappe._dict(
				reference_key="bear_standing",
				identity_key="shera",
				reference_role="Character",
				asset_version="B",
			),
		]
		analyses = {
			"B": {
				"source_asset_version": "A",
				"pose_qualification_version": 2,
				"qualified_pose_and_support": "standing upright on two supported feet with both paws down",
				"qualified_pose_view": "front",
			}
		}
		script = {"scenes": [{"cast": ["bear"], "action": "The bear waves to the camera."}]}
		planned = {
			"scene_index": 0,
			"cast_key": "bear",
			"reference_key": "bear_standing",
			"opening_pose": "standing upright on two supported feet with one paw raised in a wave",
			"view": "front",
		}
		with (
			patch(
				"frappe.db.get_value",
				side_effect=lambda _dt, name, _field: frappe.as_json(analyses.get(name, {})),
			),
			patch("joymedia.services.planning.production._ask_planner", return_value={"states": [planned]}),
		):
			state = _plan_required_states(script, selected)[0]
		self.assertEqual("bear", state["reference_key"])
		self.assertIn("one paw raised", state["opening_pose"])

	def test_product_handling_does_not_invent_a_stand_up_between_script_scenes(self):
		selected = [
			frappe._dict(
				reference_key="bear", identity_key="shera", reference_role="Character", asset_version="A"
			),
			frappe._dict(
				reference_key="bear_seated",
				identity_key="shera",
				reference_role="Character",
				asset_version="B",
			),
			frappe._dict(
				reference_key="bear_standing",
				identity_key="shera",
				reference_role="Character",
				asset_version="C",
			),
		]
		analyses = {
			"B": {
				"source_asset_version": "A",
				"pose_qualification_version": 2,
				"qualified_pose_and_support": "seated on the floor",
				"qualified_pose_view": "front",
			},
			"C": {
				"source_asset_version": "A",
				"pose_qualification_version": 2,
				"qualified_pose_and_support": "standing on supported feet",
				"qualified_pose_view": "front",
			},
		}
		script = {
			"scenes": [
				{
					"cast": ["bear"],
					"action": "The bear looks at the pack.",
					"visual_camera": "Bear seated on the floor.",
				},
				{"cast": ["bear"], "action": "The bear opens the pack."},
			]
		}
		planner_states = [
			{
				"scene_index": 0,
				"cast_key": "bear",
				"reference_key": "bear_seated",
				"opening_pose": "seated",
				"view": "front",
			},
			{
				"scene_index": 1,
				"cast_key": "bear",
				"reference_key": "bear_standing",
				"opening_pose": "standing",
				"view": "front",
			},
		]
		with (
			patch(
				"frappe.db.get_value",
				side_effect=lambda _dt, name, _field: frappe.as_json(analyses.get(name, {})),
			),
			patch(
				"joymedia.services.planning.production._ask_planner", return_value={"states": planner_states}
			),
		):
			states = _plan_required_states(script, selected)
		self.assertEqual(["bear_seated", "bear_seated"], [state["reference_key"] for state in states])

	def test_existing_view_of_same_identity_is_preferred_to_regeneration(self):
		rows = [
			{"asset_version": "seated", "identity_key": "bear", "reference_role": "Character"},
			{
				"asset_version": "upright",
				"identity_key": "bear",
				"reference_role": "Character",
				"label": "side",
			},
			{"asset_version": "stranger", "identity_key": "other", "reference_role": "Character"},
		]
		view = matching_view(
			rows,
			"seated",
			"upright_supported",
			{
				"seated": "sitting",
				"upright": "standing on two feet",
				"stranger": "standing",
			},
		)
		self.assertEqual("upright", view["asset_version"])
		self.assertIsNone(matching_view(rows, "seated", "seated_supported", {}))
		self.assertIsNone(
			matching_view(
				rows,
				"upright",
				"upright_supported",
				{
					"upright": "standing on two feet",
					"stranger": "standing",
				},
			)
		)

	def test_qualified_seated_view_replaces_unreviewed_source_with_held_prop(self):
		rows = [
			{"asset_version": "source", "identity_key": "bear", "reference_role": "Character"},
			{"asset_version": "clean", "identity_key": "bear", "reference_role": "Character"},
		]
		poses = {"source": "seated holding a heart", "clean": "seated on floor, paws empty"}
		qualified = {"clean": True}
		self.assertEqual(
			"clean", matching_view(rows, "source", "seated_supported", poses, qualified)["asset_version"]
		)
		self.assertIsNone(matching_view(rows, "clean", "seated_supported", poses, qualified))

	def test_seated_source_and_locomotion_require_an_upright_bridge(self):
		result = pose_requirement(
			"The mascot walks beside the product.",
			{"subject_motion": "locomotion"},
			["Seated on a visible floor; both feet face forward."],
		)
		self.assertTrue(result["requires_bridge_keyframe"])
		self.assertEqual("upright_supported", result["opening_pose"])
		self.assertIn("both feet", " ".join(result["constraints"]))

	def test_existing_mobile_reference_does_not_need_a_bridge(self):
		result = pose_requirement(
			"The mascot walks beside the product.",
			{"subject_motion": "locomotion"},
			["Standing on the pavement, with both feet visible."],
		)
		self.assertFalse(result["requires_bridge_keyframe"])

	def test_seated_handling_keeps_the_existing_pose(self):
		result = pose_requirement(
			"The mascot pulls one tissue from the pack.",
			{"subject_motion": "manipulation"},
			["Seated on a chair."],
		)
		self.assertEqual("preserve_reference_pose", result["opening_pose"])
		self.assertFalse(result["requires_bridge_keyframe"])

	def test_bridge_routes_only_the_character_keyframe_to_reference_conditioned_drawing(self):
		requirement = pose_requirement(
			"The mascot walks beside the product.",
			{"subject_motion": "locomotion"},
			["Seated on a visible floor; both feet face forward."],
		)
		self.assertEqual(DRAW, keyframe_character_mode(requirement, PASTE))

	def test_supported_reference_keeps_the_selected_exact_art_mode(self):
		requirement = pose_requirement(
			"The mascot pulls one tissue from the pack.",
			{"subject_motion": "manipulation"},
			["Seated on a chair."],
		)
		self.assertEqual(PASTE, keyframe_character_mode(requirement, PASTE))

	def test_product_only_shot_has_no_character_pose_constraint(self):
		result = pose_requirement(
			"Hold on the product pack for the CTA.",
			{"subject_motion": "stationary"},
			[],
			has_character=False,
		)
		self.assertEqual("not_applicable", result["opening_pose"])
		self.assertEqual([], result["constraints"])
