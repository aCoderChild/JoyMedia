import hashlib
import io
import subprocess
from unittest import TestCase
from unittest.mock import patch

import frappe
from PIL import Image

from joymedia.services.keyframes.overlay import DRAW, PASTE
from joymedia.services.planning.pose_assets import (
	_accept_pose_view,
	_body_only_pose,
	_clean_identity_source,
	_h3_pose_prompt,
	_h3_start_view,
	_observed_pose_matches,
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
	def test_masked_pose_with_lost_traits_is_not_saved_as_character_media(self):
		from joymedia.services.planning.pose_assets import _save_pose_view

		with (
			patch(
				"joymedia.services.planning.pose_assets.original_reference",
				return_value={"asset_version": "original", "file": "/original.png", "content_hash": "hash"},
			),
			patch(
				"joymedia.services.planning.pose_assets.character_look",
				return_value={"appearance": "Original identity"},
			),
			patch("joymedia.services.intake.subject_cutout.sam2_configured", return_value=True),
			patch(
				"joymedia.services.intake.subject_cutout.cutout_studio_reference",
				return_value=(b"ear removed by mask", {}),
			),
			patch.object(frappe.db, "get_value", return_value="/motion-start.png"),
			patch("joymedia.services.planning.pose_assets._accept_pose_view", return_value=False) as qualify,
			patch("joymedia.services.intake.assets.create_media_asset") as save,
		):
			with self.assertRaisesRegex(ValueError, "final masked pose"):
				_save_pose_view(
					frappe._dict(name="project"),
					frappe._dict(asset_version="start", identity_key="actor"),
					"actor",
					"seated",
					"front",
					b"raw pose",
				)
			self.assertEqual(b"ear removed by mask", qualify.call_args.args[0])
			self.assertEqual("/original.png", qualify.call_args.kwargs["identity_image"])
			save.assert_not_called()

	def test_pose_identity_is_compared_to_original_not_generated_motion_start(self):
		with (
			patch("joymedia.services.planning.pose_assets._retains_body_proportions", return_value=True),
			patch("joymedia.services.planning.pose_assets._visible_change", return_value=True),
			patch("joymedia.services.planning.pose_assets._observed_pose_matches", return_value=True),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"answer": True, "reason": "Connected and supported."},
					{"held_object_count": 0},
					{"fused_lower_body": False},
					{"answer": False, "reason": "Ear shape differs from the original."},
				],
			) as observe,
		):
			self.assertFalse(_accept_pose_view(b"candidate", b"generated start", identity_image=b"original"))
			self.assertEqual([b"original", b"candidate"], observe.call_args_list[3].args[0])

	def test_unknown_surface_is_held_even_when_broad_identity_check_passes(self):
		with (
			patch("joymedia.services.planning.pose_assets._retains_body_proportions", return_value=True),
			patch("joymedia.services.planning.pose_assets._visible_change", return_value=True),
			patch("joymedia.services.planning.pose_assets._observed_pose_matches", return_value=True),
			patch(
				"joymedia.services.planning.pose_assets.character_look",
				side_effect=[{"surface": "smooth_seamless"}, {"surface": None}],
			),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"answer": True, "reason": "Supported."},
					{"held_object_count": 0},
					{"fused_lower_body": False},
					{"answer": True, "reason": "Broad silhouette matches."},
					{"head_accessories": []},
					{"head_accessories": []},
				],
			),
		):
			self.assertFalse(_accept_pose_view(b"candidate", b"original"))

	def test_missing_original_or_reason_never_qualifies_a_pose(self):
		with patch("joymedia.services.review.consistency.ask") as observe:
			self.assertFalse(_accept_pose_view(b"candidate"))
			observe.assert_not_called()
		from joymedia.services.planning.pose_assets import _affirmed

		for observation in (
			{"answer": True},
			{"answer": 1, "reason": "same"},
			{"answer": True, "reason": 1},
			{"answer": True, "reason": ""},
		):
			self.assertFalse(_affirmed(observation))

	def test_recovered_pose_cannot_be_saved_without_qualification(self):
		from unittest.mock import Mock

		from joymedia.services.planning.pose_assets import register_pose_candidate

		project = Mock()
		source = frappe._dict(asset_version="original")
		with (
			patch("frappe.db.get_value", return_value="/original.png"),
			patch(
				"joymedia.services.planning.pose_assets.original_reference",
				return_value={"file": "/original.png", "asset_version": "original", "content_hash": "hash"},
			),
			patch("joymedia.services.planning.pose_assets._accept_pose_view", return_value=False),
			patch("joymedia.services.planning.pose_assets._save_pose_view") as save,
		):
			with self.assertRaisesRegex(ValueError, "did not pass qualification"):
				register_pose_candidate(project, source, "actor", "seated", "front", b"candidate")
			project._require_write_access.assert_called_once()
			save.assert_not_called()

	def test_h3_pose_prompt_preserves_source_anatomy_for_people_and_mascots(self):
		for pose in ("a person reaching forward", "a mascot raising one paw"):
			with self.subTest(pose=pose):
				prompt = _h3_pose_prompt(pose, "front", "")
				self.assertIn(pose, prompt)
				self.assertIn("source subject's face, body shape, limb proportions", prompt)
				self.assertNotIn("No human anatomy", prompt)
				self.assertNotIn("rounded body and short limbs", prompt)

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
			patch(
				"joymedia.services.planning.production._ask_planner",
				return_value={
					"answer": True,
					"reason": "Visible reference features and support are preserved.",
				},
			),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True, "reason": "Visible reference features and support are preserved."},
					{"held_object_count": 1, "held_objects": ["heart"]},
				],
			),
		):
			self.assertFalse(_accept_pose_view(b"generated image", b"source image"))
		with (
			patch(
				"joymedia.services.planning.production._ask_planner",
				return_value={
					"answer": True,
					"reason": "Visible reference features and support are preserved.",
				},
			),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True, "reason": "Visible reference features and support are preserved."},
					{"held_object_count": 0, "held_objects": []},
					{"fused_lower_body": False},
					{"answer": True, "reason": "Visible reference features and support are preserved."},
					{"head_accessories": []},
					{"head_accessories": []},
					{"appearance": "smooth vinyl bear", "surface": "smooth_seamless"},
					{"appearance": "smooth vinyl bear", "surface": "smooth_seamless"},
					{"distortion": False, "evidence": "Visible ears and limbs retain the original topology."},
				],
			),
		):
			self.assertTrue(_accept_pose_view(b"generated image", b"source image"))

	def test_added_head_flower_is_not_a_reusable_mascot_pose(self):
		with (
			patch(
				"joymedia.services.planning.production._ask_planner",
				return_value={
					"answer": True,
					"reason": "Visible reference features and support are preserved.",
				},
			),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True, "reason": "Visible reference features and support are preserved."},
					{"held_object_count": 0},
					{"fused_lower_body": False},
					{"answer": True, "reason": "Visible reference features and support are preserved."},
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
			patch(
				"joymedia.services.planning.production._ask_planner",
				return_value={
					"answer": True,
					"reason": "Visible reference features and support are preserved.",
				},
			),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True, "reason": "Visible reference features and support are preserved."},
					{"held_object_count": 0},
					{"fused_lower_body": False},
					{"answer": True, "reason": "Visible reference features and support are preserved."},
					{"head_accessories": []},
					{"head_accessories": []},
					{"appearance": "smooth vinyl bear", "surface": "smooth_seamless"},
					{"appearance": "smooth vinyl bear", "surface": "smooth_seamless"},
					{"eye_shape": "closed_smiling_arcs"},
					{"eye_shape": "open_dots"},
				],
			),
		):
			self.assertFalse(
				_accept_pose_view(b"generated image", b"source image", "standing on feet", "front")
			)

	def test_fused_weight_support_is_not_promoted_as_character_reference(self):
		with (
			patch(
				"joymedia.services.planning.production._ask_planner",
				return_value={
					"answer": True,
					"reason": "Visible reference features and support are preserved.",
				},
			),
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"pose_description": "standing on feet", "certainty": "high"},
					{"answer": True, "reason": "Visible reference features and support are preserved."},
					{"held_object_count": 0, "held_objects": []},
					{"fused_lower_body": True},
					{"fused_lower_body": False, "visible_leg_count": 2, "visible_foot_count": 2},
				],
			),
		):
			self.assertFalse(_accept_pose_view(b"generated image", b"source image"))

	def test_a_fused_looking_lower_body_with_two_legs_and_feet_is_the_design_not_a_stump(self):
		cases = (
			# Two distinct legs and feet: intact, whatever the source answer says.
			({"fused_lower_body": True, "visible_leg_count": 2, "visible_foot_count": 2}, None, "identity"),
			# A stump the source does not share is a collapsed generation.
			(
				{"fused_lower_body": True, "visible_leg_count": 1, "visible_foot_count": 1},
				{"fused_lower_body": False, "visible_leg_count": 2, "visible_foot_count": 2},
				"lower body",
			),
			# The same reading as the source character is its design.
			(
				{"fused_lower_body": True, "visible_leg_count": 1, "visible_foot_count": 1},
				{"fused_lower_body": True, "visible_leg_count": 1, "visible_foot_count": 1},
				"identity",
			),
		)
		for candidate, source, expected_gate in cases:
			gates = []
			answers = [
				{"answer": True, "reason": "Visible reference features and support are preserved."},
				{"held_object_count": 0},
				candidate,
			]
			answers += [source] if source else []
			answers.append({"answer": False})
			with (
				self.subTest(candidate=candidate, source=source),
				patch("joymedia.services.planning.pose_assets._retains_body_proportions", return_value=None),
				patch("joymedia.services.planning.pose_assets._visible_change", return_value=None),
				patch("joymedia.services.planning.pose_assets._observed_pose_matches", return_value=True),
				patch(
					"joymedia.services.planning.pose_assets._rejected",
					side_effect=lambda gate, *evidence: gates.append(gate) or False,
				),
				patch("joymedia.services.review.consistency.ask", side_effect=answers),
			):
				self.assertFalse(_accept_pose_view(b"generated", b"source", "seated", "front"))
			self.assertEqual([expected_gate], gates)

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
			self.assertFalse(
				_accept_pose_view(b"seated image", b"source image", pose_description="kneeling on both knees")
			)

	def test_target_led_agreement_cannot_override_failed_blind_pose_observation(self):
		with (
			patch("joymedia.services.planning.pose_assets._observed_pose_matches", return_value=False),
			patch(
				"joymedia.services.planning.pose_assets._target_pose_matches", return_value=True
			) as target_led,
		):
			self.assertFalse(
				_accept_pose_view(b"neutral image", b"source image", pose_description="one paw extended")
			)
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

	def test_localized_prop_removal_is_a_visible_pose_change(self):
		# A small held object changes materially while most studio pixels stay white.
		before = Image.new("RGB", (128, 128), "white")
		before.paste((255, 80, 130), (48, 48, 72, 72))
		after = Image.new("RGB", (128, 128), "white")
		buffers = [io.BytesIO(), io.BytesIO()]
		for image, buffer in zip((before, after), buffers, strict=True):
			image.save(buffer, format="PNG")
		self.assertTrue(_visible_change(*(buffer.getvalue() for buffer in buffers)))

	def test_codec_noise_does_not_establish_a_new_pose(self):
		buffers = [io.BytesIO(), io.BytesIO()]
		for shade, buffer in zip((250, 252), buffers, strict=True):
			Image.new("RGB", (128, 128), (shade, shade, shade)).save(buffer, format="PNG")
		self.assertFalse(_visible_change(*(buffer.getvalue() for buffer in buffers)))

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
		# The pose and its neutral same-support fallback, once each.
		self.assertEqual(2, render.call_count)

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
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False) as observe,
			patch(
				"joymedia.services.planning.pose_assets._pose_view", side_effect=ValueError("unqualified")
			) as render,
			patch("frappe.log_error"),
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual(["deferred", "deferred"], [item["status"] for item in prepared])
		# The pose and its neutral same-support fallback, once each.
		self.assertEqual(2, render.call_count)
		observe.assert_called_once()

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

	def test_unqualified_hashed_pose_cannot_bypass_visual_checks(self):
		pose = "standing with one arm forward"
		key = "pose_" + hashlib.sha256(f"person:{pose}:front".encode()).hexdigest()[:12]
		project = frappe._dict(
			name="PRJ-TEST",
			selected_media=[
				frappe._dict(
					reference_key="person",
					identity_key="person",
					reference_role="Character",
					asset_version="A",
				),
				frappe._dict(
					reference_key=key, identity_key="person", reference_role="Character", asset_version="B"
				),
			],
		)
		script = {"scenes": [{"cast": ["person"], "action": "Reach forward."}]}
		state = {"scene_index": 0, "cast_key": "person", "opening_pose": pose, "view": "front"}
		with (
			patch("joymedia.services.planning.pose_assets._plan_required_states", return_value=[state]),
			patch(
				"frappe.db.get_value",
				side_effect=lambda _dt, _name, field: "{}" if field == "analysis_json" else "/source",
			),
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False),
			patch("joymedia.services.planning.pose_assets._pose_view", side_effect=ValueError("unqualified")),
			patch("frappe.log_error"),
		):
			result = prepare_script_pose_views(project, script)
		self.assertEqual("deferred", result[0]["status"])

	def test_failed_reach_binds_closest_approved_view_with_the_same_support(self):
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
		# The reach is drawn by the first frame; the approved view anchors identity and support.
		self.assertEqual(
			("ready", "bear_standing", "standing with both paws relaxed at sides"),
			(prepared[0]["status"], prepared[0]["view"], prepared[0]["pose"]),
		)
		self.assertEqual("standing with right paw reaching forward", prepared[0]["requested_pose"])
		self.assertEqual(["bear_standing"], script["scenes"][0]["cast"])
		render.assert_called_once()

	def _standing_library_project(self, approved_pose):
		project = frappe._dict(
			name="PRJ-TEST",
			selected_media=[
				frappe._dict(
					reference_key="bear", identity_key="bear", reference_role="Character", asset_version="A"
				),
				frappe._dict(
					reference_key="bear_view",
					identity_key="bear",
					reference_role="Character",
					asset_version="B",
				),
			],
		)

		def asset_value(_doctype, name, field):
			if field == "analysis_json":
				return (
					frappe.as_json(
						{
							"source_asset_version": "A",
							"pose_qualification_version": 2,
							"qualified_pose_and_support": approved_pose,
							"qualified_pose_view": "front",
						}
					)
					if name == "B"
					else "{}"
				)
			return "/" + name

		return project, asset_value

	def test_gesture_variants_of_one_support_stop_spending_gpu_after_one_failure(self):
		project, asset_value = self._standing_library_project("standing upright, both paws free")
		script = {
			"scenes": [
				{"cast": ["bear"], "action": "The bear reaches toward a pack."},
				{"cast": ["bear"], "action": "The bear points at a puddle."},
			]
		}
		states = [
			{
				"scene_index": 0,
				"cast_key": "bear",
				"opening_pose": "standing upright, one paw near a pack",
				"view": "front",
			},
			{
				"scene_index": 1,
				"cast_key": "bear",
				"opening_pose": "standing upright, one paw near a puddle",
				"view": "front",
			},
		]
		with (
			patch("joymedia.services.planning.pose_assets._plan_required_states", return_value=states),
			patch("frappe.db.get_value", side_effect=asset_value),
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False),
			patch(
				"joymedia.services.planning.pose_assets._pose_view", side_effect=ValueError("no")
			) as render,
			patch("frappe.log_error"),
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual(["ready", "ready"], [row["status"] for row in prepared])
		self.assertEqual(["bear_view", "bear_view"], [row["view"] for row in prepared])
		render.assert_called_once()

	def test_an_unavailable_service_does_not_skip_the_other_scenes_attempts(self):
		project, asset_value = self._standing_library_project("seated on the floor, both paws free")
		script = {
			"scenes": [
				{"cast": ["bear"], "action": "The bear reaches toward a pack."},
				{"cast": ["bear"], "action": "The bear points at a puddle."},
			]
		}
		states = [
			{
				"scene_index": 0,
				"cast_key": "bear",
				"opening_pose": "standing, one paw near a pack",
				"view": "front",
			},
			{
				"scene_index": 1,
				"cast_key": "bear",
				"opening_pose": "standing, one paw near a puddle",
				"view": "front",
			},
		]
		with (
			patch("joymedia.services.planning.pose_assets._plan_required_states", return_value=states),
			patch("frappe.db.get_value", side_effect=asset_value),
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False),
			patch(
				"joymedia.services.planning.pose_assets._pose_view",
				side_effect=subprocess.TimeoutExpired("ffmpeg", 60),
			) as render,
			patch("frappe.log_error"),
		):
			prepare_script_pose_views(project, script)
		self.assertEqual(2, render.call_count)

	def test_planned_pose_is_checked_as_body_articulation_without_scene_targets(self):
		cases = [
			# A target is dropped while the support and limb geometry stay.
			(
				"seated with both paws free, reaching towards a pack",
				{"pose": "seated, both paws extended forward at chest height"},
				"seated, both paws extended forward at chest height",
			),
			# A rewrite that changes the body support is refused.
			("seated, one paw raised", {"pose": "standing, one paw raised"}, "seated, one paw raised"),
			# An unavailable planner keeps the original text.
			("seated, paws at the sides", RuntimeError("down"), "seated, paws at the sides"),
		]
		for pose, answer, expected in cases:
			with (
				self.subTest(pose=pose),
				patch(
					"joymedia.services.planning.production._ask_planner",
					**(
						{"side_effect": answer} if isinstance(answer, Exception) else {"return_value": answer}
					),
				) as planner,
			):
				cache = {}
				self.assertEqual(expected, _body_only_pose(pose, cache))
				self.assertEqual(expected, _body_only_pose(pose, cache))
				planner.assert_called_once()

	def test_blind_pose_observation_reports_limb_positions(self):
		with (
			patch("joymedia.services.review.consistency.ask", return_value={"certainty": "low"}) as ask,
			patch.object(frappe.cache, "get_value", return_value=None),
			patch("frappe.logger"),
		):
			self.assertFalse(_observed_pose_matches("/files/pose.png", "seated, paws at the sides"))
		self.assertIn("limb_positions", ask.call_args.args[1])
		self.assertNotIn("paws at the sides", ask.call_args.args[1])

	def test_a_failed_gesture_opens_on_the_neutral_pose_of_the_same_support(self):
		project, asset_value = self._standing_library_project("standing upright, both paws free")
		script = {
			"scenes": [
				{"cast": ["bear"], "action": "The bear reaches toward a pack."},
				{"cast": ["bear"], "action": "The bear points at a puddle."},
			]
		}
		states = [
			{
				"scene_index": 0,
				"cast_key": "bear",
				"opening_pose": "seated, right paw extended forward",
				"view": "front",
			},
			{
				"scene_index": 1,
				"cast_key": "bear",
				"opening_pose": "seated, left paw raised",
				"view": "front",
			},
		]
		neutral_row = frappe._dict(reference_key="pose_neutral", identity_key="bear", asset_version="N")

		def register(_project, _source, _cast, pose, _angle):
			if "relaxed" not in pose:
				raise ValueError("gesture not drawn")
			return neutral_row

		def approved_view(selected, _identity, pose, _angle):
			# The registered neutral view is the only seated approval in this library.
			return (neutral_row, {"pose": "seated relaxed"}) if neutral_row in selected else (None, None)

		with (
			patch("joymedia.services.planning.pose_assets._plan_required_states", return_value=states),
			patch("frappe.db.get_value", side_effect=asset_value),
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False),
			patch(
				"joymedia.services.planning.pose_assets._register_pose_view", side_effect=register
			) as render,
			patch(
				"joymedia.services.planning.pose_assets._approved_view_with_same_support",
				side_effect=approved_view,
			),
			patch("frappe.log_error"),
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual(["ready", "ready"], [row["status"] for row in prepared])
		self.assertEqual(["pose_neutral", "pose_neutral"], [row["view"] for row in prepared])
		self.assertEqual("seated, right paw extended forward", prepared[0]["requested_pose"])
		# One gesture attempt and one neutral attempt; the second scene reuses the result.
		self.assertEqual(2, render.call_count)

	def test_a_different_body_support_is_never_substituted(self):
		project, asset_value = self._standing_library_project("seated on the floor, both paws free")
		script = {"scenes": [{"cast": ["bear"], "action": "The bear walks to the pack."}]}
		state = {
			"scene_index": 0,
			"cast_key": "bear",
			"opening_pose": "standing upright, mid-step",
			"view": "front",
		}
		with (
			patch("joymedia.services.planning.pose_assets._plan_required_states", return_value=[state]),
			patch("frappe.db.get_value", side_effect=asset_value),
			patch("joymedia.services.planning.pose_assets._view_matches", return_value=False),
			patch("joymedia.services.planning.pose_assets._pose_view", side_effect=ValueError("no")),
			patch("frappe.log_error"),
		):
			prepared = prepare_script_pose_views(project, script)
		self.assertEqual("deferred", prepared[0]["status"])
		self.assertEqual(["bear"], script["scenes"][0]["cast"])

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
		# The second planner call asks only for the omitted pair.
		self.assertIn('[1, "bear"]', planner.call_args_list[1].args[0])

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
		prompt = planner.call_args_list[0].args[0]
		self.assertIn("walks upright toward the tissue pack", prompt)
		self.assertIn("right paw extended toward the pack", prompt)
		self.assertIn("already underway at the first frame", prompt)
		self.assertIn("do not require its later reached or held state", prompt)
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

	def test_the_writers_opening_support_decides_between_standing_and_seated(self):
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
		# The action names no support; only the authored field settles it.
		script = {
			"scenes": [
				{
					"cast": ["bear"],
					"opening_support": "standing",
					"action": "[0-2s] The bear reaches toward the pack.",
				}
			]
		}
		planned = {
			"scene_index": 0,
			"cast_key": "bear",
			"reference_key": "bear_seated",
			"opening_pose": "seated on the floor",
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
		self.assertEqual("bear_standing", state["reference_key"])

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
