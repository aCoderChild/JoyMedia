from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning import prompts
from joymedia.services.planning.creative import normalize_product_wording
from joymedia.services.review.physical_audit import (
	_product_angle_fit_findings,
	actor_count_findings,
	compare,
	frame_findings,
	obvious_geometry_results,
	opening_actor_support,
)
from joymedia.tests.planning.test_creative import sample_script

SCENE = {"human_cast": False, "has_product": True, "medium_locked": True, "close_framing": False}


class TestPhysicalAudit(FrappeTestCase):
	def test_retail_counts_come_from_physical_forms_and_unknown_forms_do_not_pass(self):
		from joymedia.services.review.physical_audit import retail_container_count

		self.assertEqual(
			0,
			retail_container_count(
				{
					"retail_container_count": 1,
					"objects": [
						{
							"physical_form": "single_loose_sheet",
							"visible_evidence": "One crumpled flexible paper sheet, with no enclosure.",
						}
					],
				}
			),
		)
		self.assertEqual(
			1,
			retail_container_count(
				{
					"objects": [
						{
							"physical_form": "enclosed_retail_volume",
							"visible_evidence": "A sealed wrapper encloses a thick stack of sheets.",
						}
					]
				}
			),
		)
		for observation in (
			{},
			{"objects": [{"physical_form": "unclear", "visible_evidence": "The object is partly hidden."}]},
			{"objects": [{"physical_form": "single_loose_sheet", "visible_evidence": ""}]},
		):
			self.assertIsNone(retail_container_count(observation))

	def test_support_is_extracted_only_from_explicit_unambiguous_opening(self):
		self.assertEqual("ground", opening_actor_support("The actor is seated on the rug beside the table."))
		self.assertEqual("work_surface", opening_actor_support("The miniature stands on the coffee table."))
		self.assertEqual("ground", opening_actor_support("The mascot is sitting on a cozy rug."))
		self.assertEqual(
			"seat", opening_actor_support("The actor sits on a small wooden chair beside a rug.")
		)
		self.assertIsNone(opening_actor_support("The actor sits on a cushion above the floor."))
		self.assertIsNone(opening_actor_support("There is a rug and a table in the room."))
		self.assertIsNone(opening_actor_support("One actor sits on the rug; another sits on the sofa."))

	def test_obvious_defect_in_any_sample_dominates_coherent_samples(self):
		def observe(picture, question, **kwargs):
			return {
				key: {
					"present": picture == b"bad" and key == "solid_intersection",
					"evidence": "Visible contact.",
				}
				for key in (
					"solid_intersection",
					"unsupported_load",
					"implausible_scale",
					"wrong_opening_support",
				)
			}

		rows = obvious_geometry_results(
			[b"good", b"bad", b"good"], opening="Actor seated on floor", ask=observe
		)
		intersection = next(r for r in rows if r["id"] == "geometry.solid_intersection")
		self.assertEqual("violated", intersection["verdict"])
		self.assertEqual([1], intersection["frames"])
		opening = next(r for r in rows if r["id"] == "geometry.wrong_opening_support")
		self.assertEqual([0], opening["frames"])

	def test_observed_table_support_is_compared_in_code_with_authored_ground_support(self):
		rows = obvious_geometry_results(
			[b"frame"],
			opening="Actor seated on the rug.",
			ask=lambda *args, **kwargs: {
				"actor_support": {"surface": "work_surface", "evidence": "Pelvis rests on tabletop."}
			},
		)
		row = next(r for r in rows if r["id"] == "geometry.wrong_opening_support")
		self.assertEqual("violated", row["verdict"])
		self.assertEqual([0], row["frames"])

	def test_malformed_or_missing_physical_evidence_is_never_a_pass(self):
		for answer in (
			{},
			{"solid_intersection": {"present": 0, "evidence": "Looks fine"}},
			{"solid_intersection": {"present": False, "evidence": ""}},
		):
			rows = obvious_geometry_results([b"candidate"], ask=lambda *args, **kwargs: answer)
			self.assertTrue(all(r["verdict"] == "uncertain" for r in rows))

	def test_coherent_physical_evidence_can_pass_without_fixed_furniture_dimensions(self):
		rows = obvious_geometry_results(
			[b"candidate"],
			ask=lambda *args, **kwargs: {
				key: {"present": False, "evidence": "Visible support and separated solid bodies."}
				for key in ("solid_intersection", "unsupported_load", "implausible_scale")
			},
		)
		self.assertTrue(all(r["verdict"] == "supported" for r in rows))

	def test_product_front_artwork_does_not_prove_scene_angle(self):
		def observe(images, question, **kwargs):
			self.assertEqual(["source", "frame"], images)
			return {"answer": False, "reason": "Box edges oppose its supporting table."}

		self.assertIn(
			"Critical geometry: advertised product camera angle conflicts with its support plane",
			_product_angle_fit_findings("source", "frame", observe),
		)
		self.assertTrue(
			any(
				"unverified" in finding
				for finding in _product_angle_fit_findings(
					"source", "frame", lambda *args, **kwargs: {"answer": None}
				)
			)
		)

	def test_independent_count_catches_a_duplicate_mascot(self):
		self.assertIn(
			"Critical prop: 2 character bodies are visible; the script declares 1.",
			actor_count_findings({"actor_instances": 2}, 1),
		)
		self.assertEqual([], actor_count_findings({"actor_instances": 1}, 1))
		self.assertTrue(any("unverified" in issue for issue in actor_count_findings({}, 1)))

	def test_real_frame_review_catches_cropped_human_at_edge(self):
		from joymedia.services.planning import shot_structure
		from joymedia.services.review import consistency

		project = frappe._dict(product_name="Shera", storyboard_source_json="{}")
		shot = frappe._dict(name="SHOT-X", shot_number=1, motion_plan_json="{}")
		observation = {
			"figures": [],
			"product_packages": 1,
			"product_placement": {
				"supported_by": "table",
				"contact": "flush",
				"perspective": "aligned",
				"scale": "plausible",
				"lighting": "matched",
			},
		}
		with (
			patch.object(frappe, "get_all", return_value=["Product"]),
			patch.object(
				consistency,
				"ask",
				side_effect=[
					observation,
					{
						"objects": [
							{
								"physical_form": "enclosed_retail_volume",
								"visible_evidence": "A sealed package with visible thickness.",
							}
						]
					},
					{"answer": False},
					{"unexpected_humans": True},
				],
			),
			patch.object(shot_structure, "structure_for", return_value={}),
			patch.object(prompts, "_mood", return_value=""),
		):
			issues = frame_findings(project, shot, "frame.png")
		self.assertTrue(any("undeclared human" in issue for issue in issues))

	def test_product_photo_background_patch_fails_physical_review(self):
		from joymedia.services.planning import shot_structure
		from joymedia.services.review import consistency

		project = frappe._dict(product_name="Shera", storyboard_source_json="{}")
		shot = frappe._dict(name="SHOT-X", shot_number=1, motion_plan_json="{}")
		observation = {
			"figures": [],
			"product_packages": 1,
			"product_placement": {
				"supported_by": "table",
				"contact": "flush",
				"perspective": "aligned",
				"scale": "plausible",
				"lighting": "matched",
			},
		}
		with (
			patch.object(frappe, "get_all", return_value=["Product"]),
			patch.object(
				consistency,
				"ask",
				side_effect=[
					observation,
					{
						"objects": [
							{
								"physical_form": "enclosed_retail_volume",
								"visible_evidence": "A sealed package with visible thickness.",
							}
						]
					},
					{"answer": True},
					{"unexpected_humans": False},
				],
			),
			patch.object(shot_structure, "structure_for", return_value={}),
			patch.object(prompts, "_mood", return_value=""),
		):
			issues = frame_findings(project, shot, "frame.png")
		self.assertTrue(any("rectangular studio-background matte" in issue for issue in issues))

	def test_product_only_shot_rejects_foreground_actor(self):
		issues = compare(
			{"figures": [{"who": "human figure", "supported_by": "floor"}]},
			cast_count=0,
			human_cast=False,
			has_product=True,
			medium_locked=False,
			close_framing=False,
		)
		self.assertTrue(any("no declared cast" in issue for issue in issues))

	def test_incomplete_observation_cannot_qualify_product_geometry(self):
		from joymedia.services.planning import shot_structure
		from joymedia.services.review import consistency

		project = frappe._dict(product_name="Shera", storyboard_source_json="{}")
		shot = frappe._dict(name="SHOT-X", shot_number=1, motion_plan_json="{}")
		with (
			patch.object(frappe, "get_all", return_value=["Product"]),
			patch.object(consistency, "ask", return_value={"figures": [], "product_packages": 1}),
			patch.object(shot_structure, "structure_for", return_value={}),
			patch.object(prompts, "_mood", return_value=""),
		):
			self.assertTrue(any("unverified" in note for note in frame_findings(project, shot, "frame.png")))

	def test_observed_body_pose_must_match_scripted_opening(self):
		description = {"figures": [{"who": "bear", "body_pose": "seated", "supported_by": "stool"}]}
		issues = compare(description, expected_pose="upright_supported", **SCENE)
		self.assertTrue(any("requires standing" in note for note in issues))
		self.assertEqual([], compare(description, expected_pose="seated_supported", **SCENE))

	def test_unreferenced_merchandise_is_rejected_in_a_product_free_opening(self):
		description = {"product_packages": 0, "other_retail_packages": 2}
		issues = compare(
			description, human_cast=False, has_product=False, medium_locked=False, close_framing=False
		)
		self.assertTrue(any("unreferenced retail packages" in note for note in issues))

	def test_table_topology_is_not_invented_from_a_fixed_leg_count(self):
		tripod = {"main_table": {"fully_visible": True, "leg_count": 3, "malformed": False}}
		self.assertEqual([], compare(tripod, **SCENE))
		occluded = {"main_table": {"fully_visible": False, "leg_count": None, "malformed": False}}
		self.assertEqual([], compare(occluded, **SCENE))
		floating = {"main_table": {"fully_visible": False, "leg_count": None, "malformed": True}}
		self.assertTrue(any("floating" in note for note in compare(floating, **SCENE)))

	def test_a_coherent_frame_has_no_findings(self):
		description = {
			"figures": [
				{
					"who": "white bear",
					"supported_by": "armchair seat",
					"passes_through": "",
					"size_vs_support": "smaller",
				}
			],
			"human_body_parts": False,
			"product_packages": 1,
			"medium": "3d_render",
			"rule_conflicts": [],
		}
		self.assertEqual([], compare(description, **SCENE))

	def test_product_only_frame_ignores_no_figure_placeholder(self):
		observed = {
			"figures": [{"who": "no figure present", "supported_by": "table"}],
			"product_packages": 1,
			"product_placement": {"supported_by": "table", "contact": "flush", "perspective": "aligned"},
		}
		self.assertEqual([], compare(observed, **SCENE))

	def test_the_armchair_frame_is_caught_on_every_axis(self):
		description = {
			"figures": [
				{
					"who": "white bear",
					"supported_by": "nothing visible",
					"passes_through": "the armchair's armrest",
					"size_vs_support": "larger",
				}
			],
			"human_body_parts": True,
			"product_packages": 2,
			"medium": "2d_illustration",
			"rule_conflicts": ["The bear must sit on the sofa seat: it hovers in front of it"],
		}
		issues = compare(description, **SCENE)
		self.assertIn("Critical geometry: white bear passes through the armchair's armrest", issues)
		self.assertIn("Critical geometry: white bear has no visible support", issues)
		self.assertIn("Critical geometry: white bear is larger than the furniture it uses", issues)
		self.assertIn("Critical prop: a human hand, arm or person appears; only the cast may act", issues)
		self.assertIn("Critical prop: 2 product packages are drawn instead of one", issues)
		self.assertTrue(any(issue.startswith("Critical style:") for issue in issues))
		self.assertTrue(any("breaks the scene rule" in issue for issue in issues))

	def test_cropped_support_humans_in_the_cast_and_a_chosen_medium_are_not_violations(self):
		description = {
			"figures": [{"who": "mother", "supported_by": "nothing visible", "passes_through": "none"}],
			"human_body_parts": True,
			"product_packages": 1,
			"medium": "2d_illustration",
		}
		self.assertEqual(
			[],
			compare(description, human_cast=True, has_product=True, medium_locked=False, close_framing=True),
		)
		# The real frame: the mascot's chest lies on the table and its legs are under it.
		table = compare(
			{
				"figures": [
					{
						"who": "bear",
						"supported_by": "table",
						"passes_through": "empty",
						"cut_by_surface": "the tabletop edge",
					}
				]
			},
			**SCENE,
		)
		self.assertIn(
			"Critical geometry: bear passes through the tabletop edge, half above and half below it", table
		)
		self.assertIn(
			"Critical geometry: bear rests on a table or work surface instead of a seat or the floor", table
		)
		self.assertIn(
			"Critical geometry: bear rests on the advertised product instead of a floor or seat",
			compare({"figures": [{"who": "bear", "supported_by": "the tissue package"}]}, **SCENE),
		)

	def test_floor_seated_actor_is_not_rejected_for_foreground_occlusion(self):
		# Two real Shera VLM descriptions: the redesigned frame has floor support,
		# yet the same model calls its adjacent table a cut and compares the mascot
		# to that table rather than the floor. The original bad frame has table
		# support, so it must still fail.
		good = {
			"figures": [
				{
					"who": "bear",
					"supported_by": "floor",
					"passes_through": "empty",
					"cut_by_surface": "table",
					"size_vs_support": "larger",
				}
			],
			"product_packages": 1,
		}
		self.assertEqual([], compare(good, **SCENE))
		bad = {
			"figures": [
				{
					"who": "bear",
					"supported_by": "table",
					"passes_through": "empty",
					"cut_by_surface": "tabletop",
					"size_vs_support": "larger",
				}
			]
		}
		self.assertTrue(any("table or work surface" in note for note in compare(bad, **SCENE)))

	def test_product_placement_is_checked_against_any_visible_environment(self):
		# These are reviewer observations, not a table- or brand-specific heuristic.
		# A package can be staged on any supplied support, provided its projective
		# geometry, depth ordering and lighting agree with that setting.
		bad = {
			"product_packages": 1,
			"product_placement": {
				"supported_by": "a display plinth",
				"contact": "floating",
				"perspective": "misaligned",
				"scale": "implausible",
				"occlusion": "implausible",
				"shadow": "missing_or_mismatched",
			},
		}
		issues = compare(bad, **SCENE)
		self.assertIn("Critical geometry: advertised product floats above its visible support", issues)
		self.assertIn(
			"Critical geometry: advertised product perspective conflicts with the environment", issues
		)
		self.assertIn("Critical geometry: advertised product scale conflicts with nearby objects", issues)
		self.assertIn(
			"Critical geometry: advertised product has an impossible foreground/background occlusion", issues
		)
		self.assertIn(
			"Critical geometry: advertised product is not grounded by a matching contact shadow", issues
		)
		self.assertIn(
			"Critical geometry: advertised product lighting or cutout edge conflicts with the environment",
			compare({"product_placement": {"lighting": "mismatched"}}, **SCENE),
		)
		coherent = {
			"product_packages": 1,
			"product_placement": {
				"supported_by": "a display plinth",
				"contact": "flush",
				"perspective": "aligned",
				"scale": "plausible",
				"occlusion": "plausible",
				"shadow": "grounded",
			},
		}
		self.assertEqual([], compare(coherent, **SCENE))


class TestRenderingMedium(FrappeTestCase):
	def mood(self, style, ai):
		with (
			patch.object(prompts, "sheet_brief", return_value={"tone": "", "style": style, "avoid": ""}),
			patch.object(prompts, "_ai_written", return_value=ai),
		):
			return prompts._mood(frappe._dict(name="PRJ-TEST"))

	def test_unanchored_or_ai_written_styles_are_pinned_to_the_reference_photos(self):
		self.assertIn(prompts.MEDIUM_LOCK, self.mood("", ai=False))
		self.assertIn(prompts.MEDIUM_LOCK, self.mood("Warm light and pastel colours", ai=False))
		self.assertIn(prompts.MEDIUM_LOCK, self.mood("Photographic living room", ai=True))
		# A medium the client chose in their own sheet is respected.
		self.assertNotIn(prompts.MEDIUM_LOCK, self.mood("3D animation, bright colours", ai=False))

	def test_the_ai_writer_cannot_choose_a_flat_drawing_medium(self):
		script = sample_script()
		script["visual_style"] = "Cute and vibrant cartoon-style animation. Warm layered practical light."
		changes = normalize_product_wording(script, [])
		self.assertEqual("Warm layered practical light.", script["visual_style"])
		self.assertTrue(any("flat drawing medium" in change for change in changes))
