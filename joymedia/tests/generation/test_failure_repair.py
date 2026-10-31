from unittest import TestCase
from unittest.mock import patch

import frappe

from joymedia.services.generation import creative_batch as cb
from joymedia.services.generation.failure_repair import apply_edits, classify, writer_notes


def script():
	return {
		"scenes": [
			{"cast": [], "products": ["pack"], "visual_camera": "The pack.", "action": "[0-2s] It rests."},
			{
				"cast": ["mascot"],
				"products": ["pack"],
				"shot_framing": "close_up",
				"visual_camera": "Close-up of the mascot holding a tissue beside the pack.",
				"action": "[0-3s] The mascot lifts the tissue out of the box.",
				"continuity_rules": "Seated on the rug.",
			},
		]
	}


class TestFailureRepair(TestCase):
	def test_recorded_evidence_names_its_failure_kinds(self):
		evidence = (
			"Critical framing: full character body appears in a close product/action detail; "
			"Critical prop: unreferenced retail packages appear in a product-free shot; "
			"Expected one unambiguous product; detected 2."
		)
		self.assertEqual(["framing", "invented_package", "pack_compositing"], classify(evidence))
		self.assertEqual([], classify("Geometry qualification remains uncertain."))

	def test_mechanical_slips_are_edited_once_and_staging_is_left_to_the_writer(self):
		edited, applied = script(), set()
		changed = apply_edits(
			edited, {2: ["framing", "pack_compositing", "invented_package", "sheet_print"]}, applied
		)
		scene = edited["scenes"][1]
		self.assertEqual([2], changed)
		self.assertEqual("close_up", scene["shot_framing"])
		self.assertTrue(
			scene["visual_camera"].startswith(
				"Close-up of the mascot holding a plain, unprinted white tissue"
			)
		)
		self.assertEqual([], scene["products"])
		self.assertNotIn("pack", scene["visual_camera"] + scene["action"])
		self.assertIn("only loose object", scene["continuity_rules"])
		self.assertEqual({"2:pack_compositing", "2:invented_package", "2:sheet_print"}, applied)
		self.assertEqual([], apply_edits(edited, {2: ["sheet_print"]}, applied))
		notes = writer_notes({2: ["framing", "sheet_print"]}, applied)
		self.assertEqual([2], [n["scene"] for n in notes])
		self.assertIn("Restage the scene", notes[0]["text"])
		self.assertEqual([], writer_notes({2: ["framing"]}, applied))

	def test_product_only_shots_keep_their_source_photograph(self):
		edited = script()
		self.assertEqual([], apply_edits(edited, {1: ["pack_compositing", "invented_package"]}, set()))
		self.assertEqual(["pack"], edited["scenes"][0]["products"])

	def test_a_staging_failure_goes_to_the_writer_once(self):
		variants = [{"status": "Keyframes", "project": "P", "script": script()}]
		shot = frappe._dict(
			name="S2",
			shot_number=2,
			consistency_status="Needs Review",
			keyframe_artifact="A",
			consistency_notes="Critical framing: full character body appears in a close product/action detail",
		)
		with (
			patch.object(cb, "_scene_failure_evidence", side_effect=lambda s: s.consistency_notes),
			patch.object(cb, "_write"),
			patch.object(cb, "_queue_rewrite") as queue,
			patch("frappe.db.commit"),
		):
			self.assertTrue(cb._start_failure_edits("CRB", variants, 0, [shot]))
			revision = variants[0]["scene_revision"]
			self.assertEqual(2, revision["notes"][0]["scene"])
			self.assertEqual("close_up", variants[0]["script"]["scenes"][1]["shot_framing"])
			self.assertEqual(["2:framing"], variants[0]["failure_edits"])
			variants[0]["status"] = "Keyframes"
			self.assertFalse(cb._start_failure_edits("CRB", variants, 0, [shot]))
		queue.assert_called_once_with("CRB", 0)

	def test_only_a_failure_the_previous_redraw_had_skips_the_next_redraw(self):
		variants = [{"status": "Keyframes", "project": "P", "script": script()}]
		shot = frappe._dict(
			name="S2",
			shot_number=2,
			consistency_status="Needs Review",
			keyframe_artifact="A",
			consistency_notes="Critical framing: full character body appears in a close product/action detail",
		)
		with (
			patch.object(cb, "_scene_failure_evidence", side_effect=lambda s: s.consistency_notes),
			patch.object(cb, "_write"),
			patch.object(cb, "_queue_rewrite"),
			patch("frappe.db.commit"),
		):
			with patch.object(cb, "_previous_failure", return_value="Critical geometry: unsupported product"):
				self.assertFalse(cb._start_failure_edits("CRB", variants, 0, [shot], repeated_only=True))
			with patch.object(cb, "_previous_failure", return_value=shot.consistency_notes):
				self.assertTrue(cb._start_failure_edits("CRB", variants, 0, [shot], repeated_only=True))


class TestSourceProductPhoto(TestCase):
	def test_only_an_unaltered_product_only_opening_counts_as_the_source_photo(self):
		def shot(*rows):
			return frappe._dict(
				generation_inputs=[frappe._dict(reference_role=r, asset_version=a) for r, a in rows]
			)

		photo = shot(("Product", "P"), ("Environment", "E"), ("first_frame", "P"))
		self.assertTrue(cb._is_source_product_photo(photo))
		self.assertFalse(cb._is_source_product_photo(shot(("Product", "P"), ("first_frame", "COMPOSED"))))
		self.assertFalse(
			cb._is_source_product_photo(shot(("Product", "P"), ("Character", "M"), ("first_frame", "P")))
		)


class TestUnstatedSupport(TestCase):
	def test_an_unstated_seat_beside_a_table_goes_back_to_the_writer(self):
		from joymedia.services.planning.creative import product_hero_defects

		def scenes(opening):
			product = {"cast": [], "products": ["p"], "duration_seconds": 2.5, "action": "[0-2.5s] Rests."}
			first = {
				"cast": ["m"],
				"products": [],
				"duration_seconds": 3,
				"visual_camera": "The mascot sits on the rug, paw raised, a tissue on the rug.",
				"action": "[0-1.5s] The mascot picks up the tissue.\n[1.5-3s] It waves it.",
			}
			second = {
				"cast": ["m"],
				"products": [],
				"duration_seconds": 3,
				"visual_camera": opening,
				"action": "[0-3s] The mascot touches the tissue to its cheek.",
			}
			return [product, first, second, dict(product)]

		with self.assertRaises(ValueError) as raised:
			product_hero_defects(scenes("The mascot is seated, with the tissue resting on a small table."))
		self.assertIn("seats the character without saying on what", str(raised.exception))
		# Whatever support the script states is its own choice.
		product_hero_defects(scenes("The mascot is seated on a stool, the tissue on a small table."))
		product_hero_defects(scenes("The mascot stands at the low table, the tissue on the table."))

	def test_an_unconfirmed_opening_is_classified_as_a_staging_failure(self):
		note = "Check that the picture shows: The tissue is resting on the table. Automatic screening could not confirm it."
		self.assertEqual(["support"], classify(note))
		self.assertIn(
			"State exactly what the character sits or stands on",
			writer_notes({3: ["support"]}, set())[0]["text"],
		)


class TestVariety(TestCase):
	def test_measured_variety_between_character_scenes(self):
		from joymedia.services.planning.creative import variety_defects

		reach = {
			"cast": ["m"],
			"shot_framing": "medium",
			"visual_camera": "The mascot is seated, right paw extended forward at chest height, facing a tissue on a rug.",
		}
		cheek = {
			"cast": ["m"],
			"shot_framing": "close_up",
			"visual_camera": "The mascot is seated, with the tissue resting on a small table within reach.",
		}
		self.assertEqual([], variety_defects([{"cast": []}, reach, cheek, {"cast": []}]))
		problems = variety_defects([reach, dict(reach), dict(reach)])
		self.assertTrue(any("share the medium framing" in p for p in problems))
		self.assertTrue(any("same pose and gesture" in p for p in problems))
		self.assertTrue(any("one body state" in p for p in problems))
		standing = dict(cheek, visual_camera="The mascot stands beside the low table, both paws raised.")
		self.assertFalse(any("one body state" in p for p in variety_defects([reach, cheek, standing])))


class TestCloseOpening(TestCase):
	def test_a_close_up_opening_that_describes_the_whole_body_goes_back_to_the_writer(self):
		from joymedia.services.planning.creative import product_hero_defects

		product = {"cast": [], "products": ["p"], "duration_seconds": 2.5, "action": "[0-2.5s] Rests."}
		first = {
			"cast": ["m"],
			"products": [],
			"shot_framing": "medium",
			"duration_seconds": 3,
			"visual_camera": "The mascot sits on the rug, paw raised, a tissue on the rug.",
			"action": "[0-1.5s] The mascot picks up the tissue.\n[1.5-3s] It waves it.",
		}
		close = {
			"cast": ["m"],
			"products": [],
			"shot_framing": "close_up",
			"duration_seconds": 3,
			# Recorded from CRB-00125 scene 3 after its restage.
			"visual_camera": "The mascot is seated on the rug, with the tissue resting on a small table within reach.",
			"action": "[0-3s] The mascot touches the tissue to its cheek.",
		}
		with self.assertRaises(ValueError) as raised:
			product_hero_defects([product, first, close, dict(product)])
		self.assertIn("describe only what the close frame shows", str(raised.exception))
		close["visual_camera"] = "Close on the mascot's paws holding a soft white tissue against its cheek."
		product_hero_defects([product, first, close, dict(product)])


class TestSpentRepeats(TestCase):
	def test_a_repeat_after_its_change_was_made_is_not_redrawn_again(self):
		shot = frappe._dict(
			name="S3",
			shot_number=3,
			consistency_status="Needs Review",
			consistency_notes="Critical framing: full character body appears in a close product/action detail",
		)
		with (
			patch.object(cb, "_scene_failure_evidence", side_effect=lambda s: s.consistency_notes),
			patch.object(cb, "_previous_failure", return_value=shot.consistency_notes),
		):
			self.assertEqual({"S3"}, cb._spent_repeats([shot], ["3:framing"]))
			self.assertEqual(set(), cb._spent_repeats([shot], ["2:framing"]))
		with (
			patch.object(cb, "_scene_failure_evidence", side_effect=lambda s: s.consistency_notes),
			patch.object(cb, "_previous_failure", return_value="Critical identity: eye design changed"),
		):
			self.assertEqual(set(), cb._spent_repeats([shot], ["3:framing"]))


class TestPosePlanOutage(TestCase):
	def test_an_unavailable_pose_planner_is_an_outage_not_a_failed_pose(self):
		from joymedia.services.planning.production import PlannerUnavailableError

		variant = {
			"pose_prepared": True,
			"pose_views": [
				{"scene": 2, "status": "deferred", "reason": "pose plan unavailable"},
				{"scene": 3, "status": "deferred", "reason": "pose plan unavailable"},
			],
		}
		with self.assertRaises(PlannerUnavailableError):
			cb._admit_pose_preparation(variant)
		self.assertFalse(variant["pose_prepared"])
		self.assertTrue(cb._service_outage(PlannerUnavailableError("x")))
		variant["pose_views"][1] = {"scene": 3, "status": "rejected", "reason": "identity changed"}
		with self.assertRaises(cb.UnverifiedPoseRequirements):
			cb._admit_pose_preparation(variant)


class TestGateRejections(TestCase):
	def test_a_gate_rejection_is_not_an_input_defect(self):
		rejected = frappe._dict(
			status="Failed",
			failure_class="Input",
			error_summary="Automatic visual checks held this scene.",
			error_details="Visual admission rejected",
		)
		broken = frappe._dict(rejected, error_details="Workflow node missing")
		task = [frappe._dict(name="T", shot="S3")]
		with patch("frappe.get_all", side_effect=[task, [rejected]]):
			self.assertIsNone(cb._nonretryable_scene_failure("RUN", ["S3"]))
		with patch("frappe.get_all", side_effect=[task, [broken]]):
			self.assertEqual("S3", cb._nonretryable_scene_failure("RUN", ["S3"])["shot"])


class TestNamedSupport(TestCase):
	def test_material_on_an_unnamed_support_goes_back_to_the_writer(self):
		from joymedia.services.planning.creative import product_hero_defects

		product = {"cast": [], "products": ["p"], "duration_seconds": 2.5, "action": "[0-2.5s] Rests."}
		first = {
			"cast": ["m"],
			"products": [],
			"shot_framing": "medium",
			"duration_seconds": 3,
			"visual_camera": "The mascot sits on the rug, paw raised, a tissue on the rug.",
			"action": "[0-1.5s] The mascot picks up the tissue.\n[1.5-3s] It waves it.",
		}
		close = {
			"cast": ["m"],
			"products": [],
			"shot_framing": "close_up",
			"duration_seconds": 3,
			# Recorded from CRB-00125 scene 3.
			"visual_camera": "Close-up of the mascot's paw near the tissue resting on a visible support.",
			"action": "[0-3s] The mascot touches the tissue to its cheek.",
		}
		with self.assertRaises(ValueError) as raised:
			product_hero_defects([product, first, close, dict(product)])
		self.assertIn("name the actual support", str(raised.exception))
		close["visual_camera"] = "Close-up of the mascot's paw beside the tissue lying on the rug."
		product_hero_defects([product, first, close, dict(product)])


class TestNewConceptBeforeStop(TestCase):
	def test_an_unusable_scene_after_spent_scene_repairs_starts_a_new_concept(self):
		import inspect

		# The final stop is reached only after a new concept was refused (its budget is spent).
		source = inspect.getsource(cb.advance_batch)
		restart = source.index("could not be drawn as written")
		stop = source.index("Automatic first-frame repair exhausted")
		self.assertLess(restart, stop)


class TestSourcePhotoScenesFirst(TestCase):
	def test_only_scenes_without_a_clip_are_left_for_generated_video(self):
		project = frappe._dict(name="P")
		shots = [
			frappe._dict(name="S1", selected_output_asset_version="PHOTO-CLIP"),
			frappe._dict(name="S2", selected_output_asset_version=None),
			frappe._dict(name="S3", selected_output_asset_version="KEPT-CLIP"),
		]
		with (
			patch.object(cb, "_compose_product_insert_fallbacks", return_value=1),
			patch("frappe.get_all", return_value=shots),
			patch("frappe.db.commit"),
		):
			self.assertEqual((["S2"], 3), cb._compose_source_photo_scenes(project, {}, "CRB", 0))
		with (
			patch.object(cb, "_compose_product_insert_fallbacks", side_effect=RuntimeError("ffmpeg")),
			patch("frappe.get_all", return_value=shots),
			patch("frappe.log_error"),
			patch("frappe.db.rollback"),
		):
			self.assertEqual((["S2"], 3), cb._compose_source_photo_scenes(project, {}, "CRB", 0))


class TestProductWordInCharacterScene(TestCase):
	def test_opening_the_product_in_a_character_scene_goes_back_to_the_writer(self):
		from joymedia.services.planning.creative import product_hero_defects

		product = {"cast": [], "products": ["p"], "duration_seconds": 2.5, "action": "[0-2.5s] Rests."}
		scene = {
			"cast": ["m"],
			"products": [],
			"shot_framing": "medium",
			"duration_seconds": 3,
			# Recorded from CRB-00126 scene 2 after its clip-stage restage.
			"visual_camera": "The mascot sits on the rug, paw raised, a tissue on the rug.",
			"action": "[0-1.5s] The mascot picks up the tissue.\n[1.5-3s] It opens the product and extracts a tissue.",
		}
		with self.assertRaises(ValueError) as raised:
			product_hero_defects([product, scene, dict(product)])
		self.assertIn("mentions 'product'", str(raised.exception))


class TestPickupWording(TestCase):
	def test_a_pickup_with_its_object_in_the_middle_is_not_prefixed_again(self):
		from joymedia.services.planning.creative import ACQUIRE, normalize_product_hero_characters

		self.assertTrue(ACQUIRE.search("reaches out with his right paw and picks it up"))
		self.assertTrue(ACQUIRE.search("picks the soft tissue up"))
		product = {"cast": [], "products": ["p"], "visual_camera": "The pack.", "action": "[0-2s] Rests."}
		scene = {
			"cast": ["m"],
			"visual_camera": "The mascot sits on the rug beside a tissue.",
			"action": "[0-3s] The mascot reaches out with his right paw towards the tissue and picks it up.",
		}
		normalize_product_hero_characters(
			{"scenes": [product, scene, dict(product)]}, {"product_hero_structure": True}
		)
		self.assertNotIn("picks up the tissue and then", scene["action"])


class TestSettleSourcePhotoScenes(TestCase):
	def test_a_photo_scene_is_approved_and_its_drawn_frame_findings_dropped(self):
		def shot(name, rows, **values):
			doc = frappe._dict(
				name=name,
				generation_inputs=[frappe._dict(reference_role=r, asset_version=a) for r, a in rows],
				keyframe_status="Pending Review",
				consistency_status="Redrawing",
				keyframe_artifact="GART",
				**values,
			)
			doc.db_set = lambda values, **kwargs: doc.update(values)
			return doc

		photo = shot("S1", [("Product", "P"), ("first_frame", "P")])
		mascot = shot("S2", [("Character", "M")])
		docs = {"S1": photo, "S2": mascot}
		with (
			patch.object(cb, "_explicit_first_frame", side_effect=lambda name: name == "S1"),
			patch("frappe.get_doc", side_effect=lambda doctype, name: docs[name]),
			patch("joymedia.services.keyframes.stage.keyframe_signature", return_value="SIG"),
			patch("joymedia.services.keyframes.stage.set_keyframe_approval") as approve,
			patch("frappe.db.commit"),
		):
			variant = {}
			self.assertTrue(cb._settle_source_photo_scenes(frappe._dict(name="P"), [photo, mascot], variant))
		approve.assert_called_once_with("P", "S1")
		self.assertEqual(
			("", None, "SIG"), (photo.consistency_status, photo.keyframe_artifact, photo.keyframe_signature)
		)
		self.assertEqual("Redrawing", mascot.consistency_status)


class TestFinalHoldIsNotAnInputDefect(TestCase):
	def test_a_final_check_hold_is_retried_not_stopped(self):
		held = frappe._dict(
			status="Failed",
			failure_class="Input",
			error_summary="Unable to normalize",
			error_details="Unable to normalize Shot output: Final visual admission held this composition; inspect its saved evidence.",
		)
		with patch("frappe.get_all", side_effect=[[frappe._dict(name="T", shot="S3")], [held]]):
			self.assertIsNone(cb._nonretryable_scene_failure("RUN", ["S3"]))


class TestNarrationFitsItsScene(TestCase):
	def test_an_overlong_line_goes_back_to_the_writer(self):
		from joymedia.services.planning.creative import narration_word_budget, product_hero_defects

		self.assertEqual(6, narration_word_budget(2.5))
		product = {"cast": [], "products": ["p"], "duration_seconds": 2.5, "action": "[0-2.5s] Rests."}
		scene = {
			"cast": ["m"],
			"products": [],
			"duration_seconds": 2.5,
			"visual_camera": "The mascot sits on the rug, paw raised, a tissue on the rug.",
			"action": "[0-1.25s] The mascot picks up the tissue.\n[1.25-2.5s] It waves it.",
			# Recorded from CRB-00126 scene 2.
			"voice_over": "Discover the softness of Shera Facial Tissue.",
		}
		with self.assertRaises(ValueError) as raised:
			product_hero_defects([product, scene, dict(product)])
		self.assertIn("keep it to at most 6 words", str(raised.exception))

	def test_a_line_that_is_still_too_long_is_shortened_at_most_twice(self):
		shot = frappe._dict(
			name="S2",
			media_project="P",
			duration_seconds=2.5,
			voice_over="Discover the softness of Shera Facial Tissue.",
		)
		shot.db_set = lambda field, value, **kwargs: shot.update({field: value})
		variant = {}
		with (
			patch("frappe.get_doc", return_value=shot),
			patch("joymedia.services.audio.plan._shot_frame_range", return_value=(60, 120)),
			patch(
				"joymedia.services.planning.production._ask_planner",
				return_value={"text": "Feel Shera's softness."},
			),
		):
			self.assertTrue(cb._shorten_narration("S2", variant))
			self.assertEqual("Feel Shera's softness.", shot.voice_over)
			self.assertTrue(cb._shorten_narration("S2", variant))
			self.assertFalse(cb._shorten_narration("S2", variant))


class TestPickupBeforeHandling(TestCase):
	def test_the_pickup_goes_into_the_first_phase_that_handles_the_material(self):
		from joymedia.services.planning.creative import normalize_product_hero_characters

		product = {"cast": [], "products": ["p"], "visual_camera": "The pack.", "action": "[0-2s] Rests."}
		# Recorded from CRB-00127 scene 2: a stand-up precedes the reach for the tissue.
		scene = {
			"cast": ["m"],
			"visual_camera": "The mascot is seated on a rug.",
			"action": "[0-1.4s] The mascot stands up from a seated position.\n[1.4-2.9s] The mascot reaches out with its right paw towards the tissue.",
		}
		normalize_product_hero_characters(
			{"scenes": [product, scene, dict(product)]}, {"product_hero_structure": True}
		)
		first, second = scene["action"].split("\n")
		self.assertEqual("[0-1.4s] The mascot stands up from a seated position.", first)
		self.assertIn("The character picks up the tissue and then reaches out", second)


class TestHeldLockIsTransient(TestCase):
	def test_a_clip_lock_held_by_another_worker_is_retried(self):
		from frappe.utils.file_lock import LockTimeoutError

		self.assertTrue(cb._transient(LockTimeoutError("joymedia-compose-shot-RUN-01514-SHOT-03075")))
		self.assertFalse(cb._transient(ValueError("Rendered scenes need attention.")))


class TestPlaceNamesALocation(TestCase):
	def test_an_object_as_the_place_goes_back_to_the_writer(self):
		from joymedia.services.planning.creative import OBJECT_ONLY_PLACE, product_hero_defects

		self.assertTrue(OBJECT_ONLY_PLACE.fullmatch("Rug"))
		self.assertTrue(OBJECT_ONLY_PLACE.fullmatch("a soft woven rug"))
		self.assertFalse(OBJECT_ONLY_PLACE.fullmatch("Bright living room with a soft rug"))
		product = {"cast": [], "products": ["p"], "duration_seconds": 2.5, "action": "[0-2.5s] Rests."}
		scene = {
			"cast": ["m"],
			"products": [],
			"duration_seconds": 3,
			# Recorded from CRB-00128.
			"place": "Rug",
			"visual_camera": "The mascot sits on the rug, paw raised, a tissue on the rug.",
			"action": "[0-1.5s] The mascot picks up the tissue.\n[1.5-3s] It waves it.",
		}
		with self.assertRaises(ValueError) as raised:
			product_hero_defects([product, scene, dict(product)])
		self.assertIn("names its place as 'Rug'", str(raised.exception))
