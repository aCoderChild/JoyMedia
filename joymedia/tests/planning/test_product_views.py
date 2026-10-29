from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from joymedia.services.planning.product_views import (
	PRODUCT_IDENTITY_QUALIFICATION_VERSION,
	_candidate_matches_requested_view,
	_candidate_matches_visible_source,
	_palette_retained,
	apply_requested_view_sequence,
	constrain_product_views,
	multiview_reconstruction_inputs,
	product_view_kind,
	product_view_requirements,
	requested_product_view,
	requested_view_sequence,
)


class TestProductViewContracts(TestCase):
	def test_opaque_photo_uses_attested_source_matte_ratio_not_canvas_crop(self):
		import frappe

		from joymedia.services.planning.product_views import _silhouette_phrase

		with (
			patch("joymedia.services.keyframes.overlay._cutout_path", return_value=None),
			patch.object(frappe.db, "get_value", return_value="SOURCE"),
			patch.object(
				frappe.cache,
				"get_value",
				return_value={
					"width_height_ratio": 1.8,
					"recipe_sha256": "RECIPE",
					"source_sha256": "SOURCE",
				},
			),
			patch("joymedia.services.consistency.retention.policy", return_value={"recipe_sha256": "RECIPE"}),
		):
			self.assertIn(
				"1.8 times as wide", _silhouette_phrase({}, ["pack"], {"pack": {"asset_version": "photo"}})
			)

	def test_matching_logo_does_not_clear_missing_print_or_changed_panel_proportions(self):
		verified = {
			"identity_retained": True,
			"proportions_retained": True,
			"shared_print_retained": True,
			"reason": "Same visible panel proportions, artwork and readable lines.",
		}
		for changes, accepted in (
			({}, True),
			({"shared_print_retained": False}, False),
			({"proportions_retained": False}, False),
			({"shared_print_retained": None}, False),
			({"reason": ""}, False),
		):
			with (
				self.subTest(changes=changes),
				patch("joymedia.services.review.consistency.ask", return_value={**verified, **changes}),
			):
				self.assertEqual(accepted, _candidate_matches_visible_source("original", b"view"))

	def test_derived_view_with_lost_metadata_cannot_replace_original_product(self):
		project = {
			"selected_media": [
				{"reference_key": "pack", "identity_key": "pack", "reference_role": "Product"},
				{
					"reference_key": "derived_front",
					"identity_key": "pack",
					"reference_role": "Product",
					"product_view": "front",
					"analysis_json": {"source_asset_version": "original", "view_geometry_verified": True},
				},
			]
		}
		plan = {"reference_keys": ["pack"], "image_prompt": "Front view of the package."}
		constrain_product_views(project, plan)
		self.assertEqual(["pack"], plan["reference_views"])
		self.assertIn("selected source view", plan["image_prompt"])
		self.assertNotIn("selected front view", plan["image_prompt"])

	def test_only_unqualified_derived_views_fail_instead_of_becoming_a_source_fallback(self):
		project = {
			"selected_media": [
				{
					"reference_key": "derived",
					"identity_key": "pack",
					"reference_role": "Product",
					"analysis_json": {"source_asset_version": "missing-original"},
				},
			]
		}
		with self.assertRaisesRegex(ValueError, "No qualified product source"):
			constrain_product_views(
				project, {"reference_keys": ["derived"], "image_prompt": "Package on rug."}
			)

	def test_explicit_angle_sequence_identifies_missing_side(self):
		direction = "Request front-left, front-right, side and top-front product views."
		self.assertEqual(
			["front_left", "front_right", "side", "top_front"],
			requested_view_sequence(direction),
		)

	def test_angle_safety_instruction_does_not_request_hidden_side(self):
		direction = (
			"Choose front-left, front-right, and top-front pack views where suitable. "
			"Do not invent hidden side printing or a second package."
		)
		self.assertEqual(
			["front_left", "front_right", "top_front"],
			requested_view_sequence(direction),
		)

	def test_generated_view_label_requires_observed_end_panel(self):
		with patch("joymedia.services.review.consistency.ask", return_value={"visible_end": "right"}):
			self.assertFalse(_candidate_matches_requested_view(b"image", "front_left"))
			self.assertTrue(_candidate_matches_requested_view(b"image", "front_right"))

	def test_client_angle_sequence_survives_script_omission(self):
		script = {
			"scenes": [
				{"products": ["pack"], "visual_camera": "The pack rests on a table."},
				{"products": ["pack"], "visual_camera": "The pack rests on a table."},
			]
		}
		apply_requested_view_sequence(script, "Show the product from front-left and top-front angles.")
		self.assertEqual([("pack", "front_left"), ("pack", "top_front")], product_view_requirements(script))

	def test_structured_script_angle_drives_preparation_without_prose_keyword(self):
		script = {
			"scenes": [
				{
					"products": ["pack"],
					"visual_camera": "A close pack shot on the table.",
					"product_view": "front_right",
				}
			]
		}
		self.assertEqual([("pack", "front_right")], product_view_requirements(script))
		self.assertEqual(
			"front_right",
			requested_product_view({"product_view": "front_right", "image_prompt": "A pack on a table"}),
		)

	def test_explicit_client_angle_overrides_director_source(self):
		script = {
			"scenes": [
				{"products": ["pack"], "visual_camera": "A pack on a table.", "product_view": "source"}
			]
		}
		apply_requested_view_sequence(script, "Show the product from a front-left angle.")
		self.assertEqual([("pack", "front_left")], product_view_requirements(script))

	def test_director_schema_requires_opening_package_angle(self):
		from joymedia.services.planning.creative import script_schema

		schema = script_schema([], {"duration_seconds": None, "fps": 24, "max_scene_frames": None})
		scene = schema["properties"]["scenes"]["items"]
		self.assertIn("product_view", scene["required"])
		self.assertIn("source", scene["properties"]["product_view"]["enum"])
		self.assertIn("front_right", scene["properties"]["product_view"]["enum"])

	def setUp(self):
		self.project = {
			"selected_media": [
				{
					"reference_key": "shera_pack_front",
					"identity_key": "shera_pack",
					"reference_role": "Product",
					"label": "Shera pack front",
				},
				{
					"reference_key": "shera_pack_side",
					"identity_key": "shera_pack",
					"reference_role": "Product",
					"label": "Shera pack side",
				},
				{
					"reference_key": "mascot_front",
					"identity_key": "shera_mascot",
					"reference_role": "Character",
					"label": "Mascot front",
				},
			]
		}

	def test_infers_only_described_product_views(self):
		self.assertEqual("front", product_view_kind(self.project["selected_media"][0]))
		self.assertEqual("side", product_view_kind(self.project["selected_media"][1]))
		self.assertEqual("source", product_view_kind({"label": "Approved pack"}))
		self.assertEqual("back", product_view_kind({"label": "front photograph", "product_view": "back"}))
		self.assertEqual("front_left", product_view_kind({"label": "Shera front-left 3/4 view"}))
		self.assertEqual("front_right", product_view_kind({"label": "Shera front-right 3/4 view"}))
		self.assertEqual("top_front", product_view_kind({"label": "Shera top/front view"}))

	def test_distinct_three_quarter_product_views_bind_separately(self):
		variants = [
			{
				"reference_key": "source",
				"identity_key": "pack",
				"reference_role": "Product",
				"product_view": "front",
			},
			{
				"reference_key": "left_three_quarter",
				"identity_key": "pack",
				"reference_role": "Product",
				"product_view": "front_left",
			},
			{
				"reference_key": "right_three_quarter",
				"identity_key": "pack",
				"reference_role": "Product",
				"product_view": "front_right",
			},
			{
				"reference_key": "top",
				"identity_key": "pack",
				"reference_role": "Product",
				"product_view": "top_front",
			},
		]
		for phrase, expected in (
			("Front-left 3/4 view of the pack", "left_three_quarter"),
			("Front-right 3/4 view of the pack", "right_three_quarter"),
			("Top/front view of the pack", "top"),
		):
			plan = {"reference_keys": ["source"], "image_prompt": phrase}
			constrain_product_views({"selected_media": variants}, plan)
			self.assertEqual([expected], plan["reference_views"], phrase)

	def test_reviewed_cutout_is_preferred_for_same_declared_angle(self):
		variants = [
			{
				"reference_key": "source",
				"identity_key": "pack",
				"reference_role": "Product",
				"product_view": "front_right",
			},
			{
				"reference_key": "cutout",
				"identity_key": "pack",
				"reference_role": "Product",
				"product_view": "front_right",
				"analysis_json": {
					"product_view_status": "operator_masked_view_unverified",
					"view_geometry_verified": True,
				},
			},
		]
		plan = {"reference_keys": ["source"], "image_prompt": "Front-right view of the pack"}
		constrain_product_views({"selected_media": variants}, plan)
		self.assertEqual(["cutout"], plan["reference_views"])
		self.assertIn("verify its outline", " ".join(plan["notes"]))

	def test_unreviewed_machine_mask_cannot_displace_the_source_view(self):
		variants = [
			{
				"reference_key": "source",
				"identity_key": "pack",
				"reference_role": "Product",
				"product_view": "front_left",
			},
			{
				"reference_key": "rough_mask",
				"identity_key": "pack",
				"reference_role": "Product",
				"product_view": "front_left",
				"analysis_json": {"subject_cutout": {"score": 0.99}},
			},
		]
		plan = {"reference_keys": ["source"], "image_prompt": "Front-left view of the pack"}
		constrain_product_views({"selected_media": variants}, plan)
		self.assertEqual(["source"], plan["reference_views"])

	def test_exact_cutout_stays_with_canonical_product_when_source_identity_is_blank(self):
		variants = [
			{
				"reference_key": "product",
				"identity_key": "",
				"reference_role": "Product",
				"product_view": "source",
			},
			{
				"reference_key": "product_cutout",
				"identity_key": "product",
				"reference_role": "Product",
				"product_view": "source",
				"analysis_json": {
					"subject_cutout": {"edge_roughness": 1.05, "visual_mask_review": {"clean": True}}
				},
			},
		]
		plan = {"reference_keys": ["product"], "image_prompt": "The pack sits on a table"}
		constrain_product_views({"selected_media": variants}, plan)
		self.assertEqual(["product_cutout"], plan["reference_views"])

	def test_studio_background_does_not_hide_wrong_product_colour(self):
		with TemporaryDirectory() as directory:
			source = np.full((200, 300, 3), 255, dtype=np.uint8)
			source[50:150, 40:260] = (240, 170, 45)  # BGR blue pack
			blue = source.copy()
			pink = source.copy()
			pink[50:150, 40:260] = (170, 110, 245)
			path = Path(directory) / "source.png"
			cv2.imwrite(str(path), source)
			self.assertTrue(_palette_retained(path, cv2.imencode(".png", blue)[1].tobytes()))
			self.assertFalse(_palette_retained(path, cv2.imencode(".png", pink)[1].tobytes()))

	def test_product_side_request_uses_matching_supplied_view(self):
		plan = {
			"reference_keys": ["shera_pack_front", "mascot_front"],
			"image_prompt": "Side view of the pack on a table",
			"notes": [],
		}
		actual = constrain_product_views(self.project, plan)
		self.assertEqual(["shera_pack_side"], actual["reference_views"])
		self.assertIn("supplied side source view", " ".join(actual["notes"]))
		self.assertIn("do not invent unseen packaging geometry", actual["image_prompt"])

	def test_authored_camera_view_survives_planner_dropping_angle(self):
		plan = {
			"reference_keys": ["shera_pack_front"],
			"image_prompt": "A pack resting on the coffee table",
			"notes": [],
		}
		actual = constrain_product_views(self.project, plan, required_view="side")
		self.assertEqual(["shera_pack_side"], actual["reference_views"])
		self.assertIn("selected side view", actual["image_prompt"])

	def test_missing_requested_back_view_falls_back_to_real_front_photo(self):
		plan = {
			"reference_keys": ["shera_pack_front"],
			"image_prompt": "Rear view of the package on a clean table",
			"notes": [],
		}
		actual = constrain_product_views(self.project, plan)
		self.assertEqual(["shera_pack_front"], actual["reference_views"])
		self.assertIn("requested back view is not supplied", " ".join(actual["notes"]))
		self.assertIn("supplied front source view", " ".join(actual["notes"]))

	def test_ai_extrapolation_is_never_described_as_an_approved_source_photo(self):
		project = {
			"selected_media": [
				self.project["selected_media"][0],
				{
					"reference_key": "candidate_side",
					"identity_key": "shera_pack",
					"reference_role": "Product",
					"product_view": "side",
					"analysis_json": {
						"product_view_status": "ai_extrapolated_candidate",
						"view_geometry_verified": True,
						"visible_source_retained": True,
						"product_identity_qualification_version": PRODUCT_IDENTITY_QUALIFICATION_VERSION,
					},
				},
			]
		}
		plan = {"reference_keys": ["shera_pack_front"], "image_prompt": "Side view of the pack"}
		with patch("joymedia.services.planning.product_views._source_pixels_locked", return_value=False):
			constrain_product_views(project, plan)
		self.assertEqual(["candidate_side"], plan["reference_views"])
		notes = " ".join(plan["notes"])
		self.assertIn("unverified AI side candidate", notes)
		self.assertIn("Human product-art review is required", notes)
		self.assertNotIn("approved side source", notes)
		# A visual identity judgment is not proof of exact printed artwork.
		locked = {"reference_keys": ["shera_pack_front"], "image_prompt": "Side view of the pack"}
		with patch("joymedia.services.planning.product_views._source_pixels_locked", return_value=True):
			constrain_product_views(project, locked)
		self.assertEqual(["shera_pack_front"], locked["reference_views"])
		self.assertIn("selected front view", locked["image_prompt"])
		self.assertNotIn("selected side view", locked["image_prompt"])

	def test_unchecked_old_ai_angle_is_not_selected(self):
		project = {
			"selected_media": [
				self.project["selected_media"][0],
				{
					"reference_key": "old_side",
					"identity_key": "shera_pack",
					"reference_role": "Product",
					"product_view": "side",
					"analysis_json": {"product_view_status": "ai_extrapolated_candidate"},
				},
			]
		}
		plan = {"reference_keys": ["shera_pack_front"], "image_prompt": "Side view of the pack"}
		constrain_product_views(project, plan)
		self.assertEqual(["shera_pack_front"], plan["reference_views"])

	def test_default_product_presentation_prefers_front_and_does_not_expand_every_variant(self):
		plan = {
			"reference_keys": ["shera_pack_side"],
			"image_prompt": "The pack sits upright on a wooden table",
			"notes": [],
		}
		actual = constrain_product_views(self.project, plan)
		self.assertEqual("source", requested_product_view(plan))
		self.assertEqual(["shera_pack_front"], actual["reference_views"])

	def test_existing_character_view_stays_selected(self):
		plan = {
			"reference_keys": ["shera_pack_front", "mascot_front"],
			"reference_views": ["mascot_front"],
			"image_prompt": "Front view of product and mascot",
			"notes": [],
		}
		actual = constrain_product_views(self.project, plan)
		self.assertEqual(["mascot_front", "shera_pack_front"], actual["reference_views"])

	def test_multiview_reconstruction_requires_real_front_plus_another_view(self):
		multi_view = {
			"selected_media": [
				self.project["selected_media"][0],
				{**self.project["selected_media"][1], "product_view": "right"},
			]
		}
		contract = multiview_reconstruction_inputs(multi_view, "shera_pack_front")
		self.assertTrue(contract["ready"])
		self.assertEqual({"front", "right"}, set(contract["views"]))

		one_photo = {"selected_media": [self.project["selected_media"][0]]}
		contract = multiview_reconstruction_inputs(one_photo, "shera_pack_front")
		self.assertFalse(contract["ready"])
		self.assertIn("at least one additional real product view", contract["reason"])

	def test_generated_view_cannot_be_counted_as_second_real_reconstruction_photo(self):
		project = {
			"selected_media": [
				self.project["selected_media"][0],
				{
					**self.project["selected_media"][1],
					"analysis_json": {"product_view_status": "ai_extrapolated_candidate"},
				},
			]
		}
		contract = multiview_reconstruction_inputs(project, "shera_pack_front")
		self.assertFalse(contract["ready"])
		self.assertEqual({"front"}, set(contract["views"]))

	def test_unverified_sheet_crop_is_intermediate_not_an_automatic_scene_view(self):
		project = {
			"selected_media": [
				self.project["selected_media"][0],
				{
					**self.project["selected_media"][1],
					"product_view": "right",
					"analysis_json": {"product_view_status": "supplied_sheet_crop_unverified"},
				},
			]
		}
		contract = multiview_reconstruction_inputs(project, "shera_pack_front")
		self.assertFalse(contract["ready"])
		self.assertEqual({"front"}, set(contract["views"]))
		plan = {"reference_keys": ["shera_pack_front"], "image_prompt": "Right view of the pack"}
		constrain_product_views(project, plan)
		self.assertEqual(["shera_pack_front"], plan["reference_views"])
		self.assertIn("requested right view is not supplied", " ".join(plan["notes"]))

	def test_geometry_review_qualifies_sheet_crop_for_requested_view(self):
		project = {
			"selected_media": [
				self.project["selected_media"][0],
				{
					**self.project["selected_media"][1],
					"product_view": "right",
					"analysis_json": {
						"product_view_status": "supplied_sheet_crop_unverified",
						"view_geometry_verified": True,
					},
				},
			]
		}
		plan = {"reference_keys": ["shera_pack_front"], "image_prompt": "Right view of the pack"}
		constrain_product_views(project, plan)
		self.assertEqual(["shera_pack_side"], plan["reference_views"])

	def test_supplied_angle_wins_over_generated_angle_and_default_uses_real_photo(self):
		generated = {
			"reference_key": "ai_front",
			"identity_key": "shera_pack",
			"reference_role": "Product",
			"product_view": "front",
			"analysis_json": {"product_view_status": "ai_extrapolated_candidate"},
		}
		project = {"selected_media": [generated, *self.project["selected_media"]]}
		plan = {"reference_keys": ["shera_pack_front"], "image_prompt": "Front view of the pack"}
		constrain_product_views(project, plan)
		self.assertEqual(["shera_pack_front"], plan["reference_views"])
		plan = {"reference_keys": ["shera_pack_front"], "image_prompt": "Pack on the table"}
		constrain_product_views(project, plan)
		self.assertEqual(["shera_pack_front"], plan["reference_views"])

	def test_script_requires_candidates_before_storyboard_only_for_named_angles(self):
		script = {
			"scenes": [
				{"products": ["shera_pack_front"], "visual_camera": "Left-side close product view"},
				{"products": ["shera_pack_front"], "action": "The pack remains upright on the table"},
				{"products": ["shera_pack_front"], "image_prompt": "rear three-quarter product shot"},
			]
		}
		self.assertEqual(
			[("shera_pack_front", "left"), ("shera_pack_front", "back")],
			product_view_requirements(script),
		)

	def test_room_camera_angle_does_not_request_an_invented_product_panel(self):
		script = {
			"scenes": [
				{
					"products": ["shera_pack_front"],
					"shot_angle": "oblique",
					"visual_camera": "Oblique view of the living room and the pack on a table",
				}
			]
		}
		self.assertEqual([], product_view_requirements(script))

	def test_side_table_does_not_request_a_side_package_panel(self):
		script = {
			"scenes": [
				{
					"products": ["shera_pack_front"],
					"image_prompt": "The Shera pack rests on a side table beside the mascot.",
					"visual_camera": "A wide view of the cozy living room.",
				}
			]
		}
		self.assertEqual([], product_view_requirements(script))
		self.assertEqual(
			"side", requested_product_view({"image_prompt": "Side view of the pack on the table"})
		)

	def test_bound_product_requires_perspective_and_support_contact(self):
		plan = {"reference_keys": ["shera_pack_front"], "image_prompt": "Pack on a wooden table"}
		constrain_product_views(self.project, plan)
		self.assertIn("receding edges with the support plane", plan["image_prompt"])

	def test_a_source_pixel_lock_is_told_its_acceptance_conditions_on_the_first_drawing(self):
		for policy, expected, absent in (
			({"recipe_sha256": "x"}, "not held, lifted or covered", "load-bearing grip"),
			(None, "load-bearing grip", "not held, lifted or covered"),
		):
			plan = {"reference_keys": ["shera_pack_front"], "image_prompt": "Pack on a wooden table"}
			with (
				self.subTest(locked=bool(policy)),
				patch("joymedia.services.consistency.retention.policy", return_value=policy),
			):
				constrain_product_views(self.project, plan)
			self.assertIn(expected, plan["image_prompt"])
			self.assertNotIn(absent, plan["image_prompt"])


class TestUnheldOpening(TestCase):
	def test_a_held_locked_product_is_rewritten_to_rest_untouched_and_checked(self):
		from joymedia.services.planning.product_views import _unheld_opening

		held = "The bear is seated, holding the pack open with one paw."
		cases = (
			(
				{"image_prompt": "The bear is seated; the pack rests on the floor in front of it."},
				"rests on the floor",
			),
			({"image_prompt": "The bear still holding the pack."}, held),
			(RuntimeError("planner offline"), held),
		)
		for answer, expected in cases:
			notes = []
			with (
				self.subTest(answer=answer),
				patch(
					"joymedia.services.planning.production._ask_planner",
					**(
						{"side_effect": answer} if isinstance(answer, Exception) else {"return_value": answer}
					),
				),
			):
				self.assertIn(expected, _unheld_opening(held, notes))
			self.assertEqual(1, len(notes))

	def test_an_unheld_opening_costs_no_planner_call(self):
		from joymedia.services.planning.product_views import _unheld_opening

		with patch("joymedia.services.planning.production._ask_planner") as planner:
			self.assertEqual(
				"The pack rests on the table.", _unheld_opening("The pack rests on the table.", [])
			)
		planner.assert_not_called()


class TestProductSilhouette(TestCase):
	def test_the_prompt_states_the_cutouts_measured_proportions(self):
		import tempfile

		from PIL import Image

		from joymedia.services.planning.product_views import _silhouette_phrase

		for size, expected in (
			((360, 200), "1.8 times as wide"),
			((100, 250), "2.5 times as tall"),
			((100, 100), "as wide as it is tall"),
		):
			with tempfile.NamedTemporaryFile(suffix=".png") as handle:
				canvas = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
				canvas.paste(Image.new("RGBA", size, (90, 160, 220, 255)), (20, 30))
				canvas.save(handle.name)
				rows = {"pack": {"asset_version": "AV"}}
				with patch("joymedia.services.keyframes.overlay._cutout_path", return_value=handle.name):
					self.assertIn(expected, _silhouette_phrase(None, ["pack"], rows))
