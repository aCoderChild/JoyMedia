from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation import creative_batch as cb


def shot(number, status, notes=""):
	return frappe._dict(shot_number=number, consistency_status=status, consistency_notes=notes)


class TestAutomaticSceneRepair(FrappeTestCase):
	def test_exhausted_close_framing_can_restage_without_removing_actions(self):
		notes = cb._scene_repair_notes(
			[
				shot(
					2,
					"Needs Review",
					"Critical framing: full character body appears in a close product/action detail",
				)
			]
		)
		self.assertEqual([2], [n["scene"] for n in notes])
		self.assertIn("medium/full", notes[0]["text"])
		self.assertIn("shot_framing and visual_camera", notes[0]["text"])
		self.assertIn("Keep every actual action", notes[0]["text"])

	def test_source_art_cutaway_preserves_material_actions_and_refuses_package_handling(self):
		script = {
			"scenes": [
				{"cast": ["mascot"], "products": ["pack"], "action": "Pick up the loose tissue."},
				{"cast": ["mascot"], "products": [], "action": "Fold the tissue."},
				{"cast": ["mascot"], "products": [], "action": "Examine the tissue crease."},
				{
					"cast": ["mascot"],
					"products": ["pack"],
					"action": "The mascot places the tissue on the rug and looks at the pack.",
				},
			]
		}
		notes = cb._source_art_cutaway_notes(script)
		self.assertEqual([1, 3, 4], [n["scene"] for n in notes])
		self.assertIn(script["scenes"][-1]["action"], notes[-2]["text"])
		self.assertIn("exact original supplied product photograph", notes[-1]["text"])
		script["scenes"][0]["action"] = "The mascot lifts the pack and takes a tissue."
		self.assertEqual([], cb._source_art_cutaway_notes(script))
		script["scenes"][0]["action"] = "The mascot lifts it while holding a tissue."
		self.assertEqual([], cb._source_art_cutaway_notes(script))

	def test_legacy_product_conditioning_is_replanned_only_for_explicit_empty_rosters(self):
		project = MagicMock()
		project.name = "project"
		project.storyboard_source_json = "{}"
		shots = {
			name: frappe._dict(name=name, generation_inputs=[frappe._dict(reference_role="Product")])
			for name in ("S1", "S2")
		}
		variant = {
			"script": {"scenes": [{"products": ["pack"]}, {"products": []}]},
			"keyframe_request": {"run": "old"},
		}

		def replan(project, wanted, apply):
			self.assertEqual({"S2"}, wanted)
			self.assertTrue(apply)
			shots["S2"].generation_inputs = []

		with (
			patch("frappe.get_all", return_value=["S1", "S2"]),
			patch("frappe.get_doc", side_effect=lambda dt, name: shots[name]),
			patch("frappe.db.commit"),
			patch("joymedia.api.storyboard._plan_project", side_effect=replan),
			patch("joymedia.services.scene.registry.project_reference_registry", return_value=[]),
			patch(
				"joymedia.services.planning.reference_plan.build_reference_plan",
				return_value={"environments": []},
			),
			patch.object(cb, "_start_keyframes") as start,
			patch.object(cb, "_write"),
		):
			self.assertTrue(
				cb._recover_unlisted_products(frappe._dict(name="batch"), [variant], 0, project, {})
			)
			start.assert_called_once()
			self.assertFalse(
				cb._recover_unlisted_products(frappe._dict(name="batch"), [variant], 0, project, {})
			)
		self.assertEqual(1, len(shots["S1"].generation_inputs))
		self.assertEqual(["S2"], variant["empty_roster_replans"])
		self.assertEqual("old", variant["recovery_events"][0]["previous_run"])
		self.assertEqual([], variant["reference_plan"]["environments"])

	def test_pose_shortfall_replans_once_and_rechecks_media_for_new_script(self):
		variant = {
			"script": {"scenes": [{"beat_name": "Open"}]},
			"automatic_script_redraws": cb.AUTOMATIC_SCRIPT_REDRAWS,
			"pose_views": [{"scene": 2, "status": "deferred"}],
			"pose_prepared": True,
			"product_views_prepared": True,
			"product_views": [{"view": "left"}],
			"product_cutouts": [{"view": "source"}],
		}
		self.assertTrue(cb._restart_script_after_pose_shortfall(variant))
		self.assertIn("scenes 2", variant["revision"]["notes"][1]["text"])
		instruction = variant["revision"]["notes"][0]["text"]
		self.assertIn("source-faithful character cutaway may be static", instruction)
		self.assertNotIn("Every non-final shot must complete", instruction)
		self.assertEqual(cb.AUTOMATIC_SCRIPT_REDRAWS + 1, variant["automatic_script_redraws"])
		self.assertEqual(1, variant["pose_script_redraws"])
		for key in (
			"pose_prepared",
			"pose_views",
			"product_views_prepared",
			"product_views",
			"product_cutouts",
		):
			self.assertNotIn(key, variant)
		self.assertFalse(cb._restart_script_after_pose_shortfall(variant))

	def test_pose_replan_names_verified_alternatives(self):
		variant = {
			"project": "PRJ-test",
			"script": {"scenes": [{"beat_name": "Open"}]},
			"pose_views": [{"scene": 1, "status": "deferred", "pose": "seated with free paws"}],
		}
		project = frappe._dict(
			selected_media=[
				frappe._dict(
					reference_role="Character",
					identity_key="bear",
					reference_key="bear_front",
					asset_version="ASTV-test",
				)
			]
		)
		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe, "get_doc", return_value=project),
			patch.object(
				frappe.db,
				"get_value",
				return_value='{"source_asset_version":"ASTV-source",'
				'"pose_qualification_version":2,"qualified_pose_and_support":"standing with free paws",'
				'"qualified_pose_view":"front"}',
			),
		):
			self.assertTrue(cb._restart_script_after_pose_shortfall(variant))
		note = variant["revision"]["notes"][1]["text"]
		self.assertIn("identity bear: standing with free paws (front view)", note)
		self.assertIn("opening composition AND action", note)

	def test_unverified_script_pose_stops_before_first_frame(self):
		cb._require_verified_pose_views([{"scene": 1, "status": "ready"}])
		with self.assertRaisesRegex(cb.UnverifiedPoseRequirements, "scenes 2, 4"):
			cb._require_verified_pose_views(
				[
					{"scene": 4, "status": "deferred"},
					{"scene": 2, "status": "deferred"},
					{"scene": 4, "status": "deferred"},
				]
			)
		with self.assertRaisesRegex(
			cb.UnverifiedPoseRequirements, "Required body state: seated with free hands"
		):
			cb._require_verified_pose_views(
				[{"scene": 1, "status": "deferred", "pose": "seated with free hands"}]
			)

	def test_unverified_pose_still_blocks_after_script_replan(self):
		variant = {
			"pose_script_redraws": cb.AUTOMATIC_POSE_SCRIPT_REDRAWS,
			"pose_views": [{"scene": 2, "status": "deferred", "pose": "seated with free hands"}],
			"script": {"director_notes": []},
		}
		with self.assertRaises(cb.UnverifiedPoseRequirements):
			cb._admit_pose_preparation(variant)
		with self.assertRaises(cb.UnverifiedPoseRequirements):
			cb._admit_pose_preparation({**variant, "pose_script_redraws": 0})

	def test_revision_cannot_import_unverified_pose(self):
		variant = {"pose_views": [{"scene": 1, "status": "deferred", "pose": "standing"}]}
		with self.assertRaises(cb.UnverifiedPoseRequirements):
			cb._admit_revised_pose_preparation(variant, {"scenes": [{"action": "Stand."}]})

	def test_revision_checks_transition_after_pose_qualification(self):
		variant = {
			"pose_views": [
				{"scene": 1, "status": "ready", "source": "actor", "pose": "seated on the floor"},
				{"scene": 2, "status": "ready", "source": "actor", "pose": "standing upright"},
			]
		}
		script = {"scenes": [{"action": "Looks at the product."}, {"action": "Waves."}]}
		with self.assertRaisesRegex(ValueError, "unsupported body transition"):
			cb._admit_revised_pose_preparation(variant, script)
		script["scenes"][0]["action"] = "The actor stands up."
		cb._admit_revised_pose_preparation(variant, script)

	def test_selected_pose_cannot_jump_from_seated_to_upright(self):
		script = {
			"scenes": [
				{"action": "The mascot opens the pack."},
				{"action": "The mascot wipes the table."},
			]
		}
		views = [
			{"scene": 1, "source": "actor", "pose": "seated on the floor"},
			{"scene": 2, "source": "actor", "pose": "standing upright on two feet"},
		]
		self.assertIn("without a visible transition", cb._pose_transition_defects(script, views)[0])
		script["scenes"][0]["action"] = "The mascot opens the pack and stands up."
		self.assertEqual([], cb._pose_transition_defects(script, views))

	def test_new_concept_clears_media_preparation_from_rejected_script(self):
		variant = {
			"script": {"scenes": [{"beat_name": "First"}]},
			"pose_prepared": True,
			"pose_views": [{"scene": 1, "status": "ready"}],
			"product_views_prepared": True,
			"product_views": [{"view": "front"}],
			"product_cutouts": [{"view": "source"}],
		}
		self.assertTrue(cb._restart_automatic_script_variant(variant, variant["script"], ["wrong support"]))
		for key in (
			"pose_prepared",
			"pose_views",
			"product_views_prepared",
			"product_views",
			"product_cutouts",
		):
			self.assertNotIn(key, variant)

	def test_only_scenes_with_a_clear_frame_error_get_a_rewrite_note(self):
		notes = cb._scene_repair_notes(
			[
				shot(1, "Passed"),
				shot(3, "Needs Review", "Critical geometry: character stands on the advertised product"),
				shot(4, "Needs Review", "Physical staging review: possible prop fused"),
				shot(6, "Needs Review", "Lighting note; Critical prop: a human hand appears"),
			]
		)
		# Geometry is redrawn first, then restaged if the redraw budget is spent.
		# Scene 6's stray hand is the picture model's error: it is redrawn, not rewritten.
		self.assertEqual([3], [note["scene"] for note in notes])
		self.assertIn("stands on the advertised product", notes[0]["text"])

	def test_geometry_is_redrawn_before_a_scene_rewrite(self):
		shots = [
			shot(2, "Needs Review", "Critical style: the frame is a flat 2D illustration"),
			shot(3, "Needs Review", "Critical prop: 2 product packages are drawn instead of one"),
			shot(4, "Needs Review", "Critical geometry: bear passes through the armrest"),
		]
		for row, name in zip(shots, ("S2", "S3", "S4"), strict=True):
			row.name = name
		corrections = cb._frame_corrections(shots)
		self.assertEqual({"S2", "S3", "S4"}, set(corrections))
		self.assertTrue(corrections["S2"][0].startswith("Critical style:"))
		self.assertIn("passes through the armrest", corrections["S4"][0])
		self.assertEqual([4], [note["scene"] for note in cb._scene_repair_notes(shots)])
		shots[2].consistency_notes = "Critical geometry: bear passes through the tabletop"
		self.assertIn("Preserve the authored pose and support", cb._scene_repair_notes(shots)[0]["text"])
		self.assertNotIn("actor standing", cb._scene_repair_notes(shots)[0]["text"])

	def test_frame_corrections_redraw_only_those_frames_within_their_budget(self):
		variants = [{"status": "Keyframes", "project": "PRJ-TEST"}]
		batch = frappe._dict(name="CRB-TEST", request_json="{}")
		project = frappe._dict(name="PRJ-TEST", generation_pipeline=None)
		writes = []
		with (
			patch.object(cb, "_write"),
			patch.object(cb, "_seal_automatic_plan") as seal,
			patch.object(cb, "pinned_execution", side_effect=lambda *a: nullcontext()),
			patch.object(cb, "delivery_context", side_effect=lambda *a: nullcontext()),
			patch("joymedia.services.keyframes.stage.generate_keyframes", return_value={"run": "R"}) as draw,
			patch("frappe.cache.lock", side_effect=lambda *a, **k: nullcontext()),
			patch("frappe.db.commit"),
			patch("frappe.db.get_value", return_value="Rendering"),
			patch("frappe.db.set_value", side_effect=lambda *a, **k: writes.append(a)),
		):
			fix = {"S2": ["Critical style: the frame is a flat 2D illustration"]}
			for _ in range(cb.AUTOMATIC_FRAME_CORRECTIONS):
				self.assertTrue(cb._start_frame_corrections(batch, variants, 0, project, fix))
			self.assertFalse(cb._start_frame_corrections(batch, variants, 0, project, fix))
		self.assertEqual(cb.AUTOMATIC_FRAME_CORRECTIONS, draw.call_count)
		self.assertEqual(["S2"], draw.call_args.args[1])
		# The plan is re-approved first, so the redraw is not refused as an unapproved plan.
		self.assertEqual(cb.AUTOMATIC_FRAME_CORRECTIONS, seal.call_count)
		# The finding travels as a retry note; the scene's own direction is never edited.
		self.assertEqual(("Shot", "S2"), writes[0][:2])
		self.assertEqual("Redrawing", writes[0][2]["consistency_status"])
		self.assertNotIn("image_prompt", writes[0][2])

	def test_the_retry_note_reaches_only_the_still_image_prompt(self):
		from joymedia.services.planning.prompts import _keyframe_retry_direction

		for note, words in (
			("Critical geometry: bear passes through the tabletop", "No solid surface may run through"),
			("Critical style: the frame is a flat 2D illustration", "actual rendering medium"),
			(
				"Product lock: Product view is incompatible with the supplied source photograph.",
				"same orientation",
			),
			("Critical prop: a human hand, arm or person appears", "Show only the supplied cast"),
		):
			self.assertIn(
				words,
				_keyframe_retry_direction({"consistency_status": "Redrawing", "consistency_notes": note}),
			)

	def test_repair_rewrites_in_place_until_its_budget_then_defers_to_a_new_concept(self):
		variants = [{"status": "Keyframes", "project": "PRJ-TEST", "script": {"scenes": []}}]
		note = [{"scene": 2, "text": "Restage scene 2."}]
		with patch.object(cb, "_write"), patch("frappe.enqueue") as enqueue, patch("frappe.db.commit"):
			for _ in range(cb.AUTOMATIC_SCENE_REWRITES):
				variants[0]["status"] = "Keyframes"
				self.assertTrue(cb._start_automatic_scene_repair("CRB-TEST", variants, 0, note))
			self.assertEqual("Rewriting", variants[0]["status"])
			self.assertEqual(note, variants[0]["scene_revision"]["notes"])
			self.assertFalse(cb._start_automatic_scene_repair("CRB-TEST", variants, 0, note))
			self.assertFalse(cb._start_automatic_scene_repair("CRB-TEST", variants, 0, []))
		self.assertEqual(cb.AUTOMATIC_SCENE_REWRITES, enqueue.call_count)
		self.assertEqual(
			"joymedia.services.generation.creative_batch.rewrite_scenes_in_place", enqueue.call_args.args[0]
		)

	def test_scheduler_requeues_a_rewrite_whose_job_was_lost(self):
		batch = frappe._dict(
			name="CRB-LOST",
			owner="user@example.invalid",
			variants_json='[{"status":"Rewriting"},{"status":"Rewriting"}]',
		)
		with (
			patch.object(cb.frappe, "get_all", return_value=[batch.name]),
			patch.object(cb.frappe, "get_doc", return_value=batch),
			patch.object(cb, "partner_batch_waits_for_gpu", return_value=False),
			patch.object(cb, "_queue_prepare"),
			patch.object(cb, "is_render_alive", side_effect=lambda job: job.endswith(":1")),
			patch.object(cb.frappe, "enqueue") as enqueue,
		):
			cb.advance_batches()
		enqueue.assert_called_once()
		self.assertEqual(
			"joymedia.services.generation.creative_batch.rewrite_scenes_in_place", enqueue.call_args.args[0]
		)
		self.assertEqual(0, enqueue.call_args.kwargs["position"])

	def test_a_new_concept_starts_with_a_full_repair_budget(self):
		variant = {
			"status": "Keyframes",
			"project": "PRJ-TEST",
			"workbook": "/private/files/w.xlsx",
			"automatic_scene_rewrites": cb.AUTOMATIC_SCENE_REWRITES,
			"frame_corrections": {"S1": cb.AUTOMATIC_FRAME_CORRECTIONS},
			"physical_audit": {"S1": "GART-1"},
			"source_art_cutaway_version": 3,
		}
		self.assertTrue(cb._restart_automatic_script_variant(variant, {"scenes": []}, ["Scene 1 failed."]))
		for key in (
			"automatic_scene_rewrites",
			"frame_corrections",
			"physical_audit",
			"project",
			"source_art_cutaway_version",
		):
			self.assertNotIn(key, variant)


class TestProductViewCorrection(FrappeTestCase):
	def test_a_frame_the_product_lock_rejected_is_redrawn_with_its_rejection_as_the_correction(self):
		attempts = {
			"T1": [
				frappe._dict(
					status="Failed",
					error_details="Product view is incompatible with the supplied source photograph.",
				)
			],
			"T2": [frappe._dict(status="Failed", error_details="Visual admission rejected")],
		}

		def get_all(doctype, filters=None, **kwargs):
			if doctype == "Generation Task":
				return [frappe._dict(name="T1", shot="S1"), frappe._dict(name="T2", shot="S2")]
			return attempts[filters["generation_task"]]

		with (
			patch("frappe.get_all", side_effect=get_all),
			patch.object(cb, "_mark_for_corrected_redraw") as mark,
		):
			self.assertEqual(["S1"], cb._correct_product_views("RUN-TEST", ["S1", "S2"]))
		mark.assert_called_once_with(
			"S1", ["Product lock: Product view is incompatible with the supplied source photograph."]
		)


class TestPackshotFallback(FrappeTestCase):
	def packshot(self, roles):
		doc = frappe._dict(generation_inputs=[])
		doc.append = lambda field, row: doc.generation_inputs.append(row)
		doc.save = lambda **kwargs: None
		with (
			patch.object(cb, "_explicit_first_frame", return_value=None),
			patch(
				"joymedia.services.scene.contract.read_contract",
				return_value={"entities": [{"label": "advertised product"}, {"label": "setting"}]},
			),
			patch(
				"frappe.get_all",
				return_value=[frappe._dict(reference_role=role, asset_version="ASTV-P") for role in roles],
			),
			patch("frappe.get_doc", return_value=doc),
		):
			used = cb._use_product_source_for_packshot(
				frappe._dict(name="S6", consistency_status="Not Checked", motion_plan_json="{}"),
				without_frame=True,
			)
		return used, doc.generation_inputs

	def test_a_packshot_the_product_lock_rejected_opens_on_the_product_photo(self):
		used, inputs = self.packshot(["Product"])
		self.assertTrue(used)
		self.assertEqual([{"reference_role": "first_frame", "asset_version": "ASTV-P"}], inputs)
		# A scene with a character is never replaced by a still product photo.
		self.assertFalse(self.packshot(["Product", "Character"])[0])

	def test_every_product_lock_geometry_rejection_is_correctable(self):
		self.assertIn("Original source cannot fit the detected footprint.", cb.PRODUCT_VIEW_FAILURES)
		self.assertIn("Product is cropped at the scene edge.", cb.PRODUCT_VIEW_FAILURES)
		self.assertIn("Source product view changes its measured scene footprint;", cb.PRODUCT_VIEW_FAILURES)


class TestFailedSceneRewrite(FrappeTestCase):
	def run_failed_rewrite(self, mode):
		variants = [
			{
				"status": "Rewriting",
				"project": "PRJ-T",
				"script": {"scenes": []},
				"scene_revision": {"notes": []},
			}
		]
		batch = frappe._dict(
			name="CRB-T",
			owner="Administrator",
			status="Rendering",
			request_json=frappe.as_json({"delivery_mode": mode}),
			variants_json=frappe.as_json(variants),
		)
		written = {}
		with (
			patch(
				"frappe.get_doc",
				side_effect=lambda doctype, name=None: batch
				if doctype == "Creative Batch"
				else frappe._dict(name="PRJ-T"),
			),
			patch("frappe.set_user"),
			patch("frappe.db.rollback"),
			patch("frappe.log_error"),
			patch(
				"joymedia.services.planning.creative.draft_script", side_effect=ValueError("still invalid")
			),
			patch.object(cb, "_write", side_effect=lambda name, rows, *a, **k: written.update(rows=rows)),
		):
			cb.rewrite_scenes_in_place("CRB-T", 0)
		return written["rows"][0]

	def test_an_automatic_video_returns_to_its_pictures_instead_of_stopping(self):
		variant = self.run_failed_rewrite("automatic")
		self.assertEqual("Keyframes", variant["status"])
		self.assertIsNone(variant["scene_revision"])
		self.assertIn("still invalid", variant["repair_failures"][0])

	def test_an_assisted_video_stops_with_the_real_reason(self):
		variant = self.run_failed_rewrite("assisted")
		self.assertEqual("Needs Attention", variant["status"])
		self.assertTrue(variant["error"].startswith("Scene rewrite failed: still invalid"))


class TestRenderLinkOutage(FrappeTestCase):
	def test_a_dropped_gpu_link_is_waited_out_not_reported(self):
		self.assertTrue(cb._transient(frappe.ValidationError("Unable to connect to ComfyUI: timed out")))
		self.assertFalse(
			cb._transient(ValueError("Product view is incompatible with the supplied source photograph."))
		)


class TestFinishPreviousConcept(FrappeTestCase):
	def test_an_unwritable_last_concept_finishes_the_newest_drawn_one(self):
		variant = {
			"status": "Planning",
			"history": [
				{"project": "PRJ-OLD", "script": {"scenes": [1]}, "workbook": "/old.xlsx"},
				{"project": "PRJ-NEW", "script": {"scenes": [2]}, "workbook": "/new.xlsx"},
				{"project": "PRJ-EMPTY", "script": None},
			],
		}
		drawn = {"PRJ-OLD", "PRJ-NEW"}
		with (
			patch(
				"frappe.db.exists",
				side_effect=lambda doctype, filters=None: True
				if doctype == "Media Project"
				else filters["media_project"] in drawn,
			),
		):
			self.assertTrue(cb._finish_previous_concept(variant))
		self.assertEqual(
			("PRJ-NEW", "Keyframes", True),
			(variant["project"], variant["status"], variant["repairs_exhausted"]),
		)
		self.assertFalse(
			cb._start_frame_corrections(None, [variant], 0, None, {"S1": ["Critical style: flat"]})
		)
		with patch("frappe.db.exists", return_value=False):
			self.assertFalse(cb._finish_previous_concept({"history": [{"project": "PRJ-X", "script": {}}]}))


class TestStaleKeyframe(FrappeTestCase):
	def test_a_frame_that_no_longer_matches_its_scene_is_redrawn(self):
		shot = frappe._dict(name="S1", keyframe_artifact="GART-1", keyframe_signature="old")
		with (
			patch("frappe.get_doc", return_value=shot),
			patch("joymedia.services.keyframes.stage.keyframe_signature", return_value="new"),
		):
			self.assertTrue(cb._stale_keyframe("S1"))
		with (
			patch("frappe.get_doc", return_value=shot),
			patch("joymedia.services.keyframes.stage.keyframe_signature", return_value="old"),
		):
			self.assertFalse(cb._stale_keyframe("S1"))
		# A scene with no picture at all is handled by the missing-frame path, not this one.
		with (
			patch(
				"frappe.get_doc", return_value=frappe._dict(keyframe_artifact=None, keyframe_signature="x")
			),
			patch("joymedia.services.keyframes.stage.keyframe_signature", return_value="y"),
		):
			self.assertFalse(cb._stale_keyframe("S2"))


class TestEmptyRosterPackageRepair(FrappeTestCase):
	def test_the_rewrite_names_each_scene_whose_text_shows_an_unlisted_package(self):
		script = {
			"scenes": [
				{"products": ["product"], "visual_camera": "The pack sits on the rug."},
				{"products": [], "visual_camera": "The paw holds a tissue, the pack visible behind it."},
				{"products": [], "visual_camera": "A close-up of the tissue; no pack in frame."},
			]
		}
		defect = cb._empty_roster_package_defect(script)
		self.assertTrue(defect.startswith("Scenes 2 declare products=[]"))
		self.assertIn("list the product", defect)


class TestPackFreeActorCutaway(FrappeTestCase):
	def script(self):
		return {
			"scenes": [
				{
					"cast": ["mascot"],
					"products": ["pack"],
					"action": "The mascot pulls a tissue from the pack.",
				},
				{"cast": ["mascot"], "products": [], "action": "The mascot feels the tissue."},
				{"cast": ["mascot"], "products": ["pack"], "action": "The mascot sets the tissue down."},
			]
		}

	def test_package_handling_moves_out_of_actor_shots_into_a_source_photo_close(self):
		script = self.script()
		self.assertEqual([], cb._source_art_cutaway_notes(script))
		notes = cb._pack_free_actor_notes(script)
		self.assertEqual([1, 2, 2, 3], [n["scene"] for n in notes])
		self.assertIn("already out", notes[0]["text"])
		self.assertIn(script["scenes"][-1]["action"], notes[1]["text"])
		self.assertEqual(cb.PRODUCT_ONLY_CLOSE, notes[-1]["text"])
		# The scene receiving the moved actions is told to stay package-free too.
		self.assertIn(cb.PACK_FREE_ACTOR_SHOT, [n["text"] for n in notes if n["scene"] == 2])

	def test_repeated_pack_compositing_failures_in_an_actor_shot_trigger_the_cutaway(self):
		script = self.script()
		script["scenes"][2]["cast"] = []  # A product-only close is not an actor shot.
		variants = [{"status": "Keyframes", "script": script, "automatic_scene_rewrites": 2}]
		shots = [
			frappe._dict(name="PACKSHOT", shot_number=3, consistency_notes=""),
			frappe._dict(
				name="ACTOR",
				shot_number=1,
				consistency_notes="Critical geometry: advertised product camera angle conflicts with its support plane",
			),
		]
		failed = [frappe._dict(error_details="Expected one unambiguous product; detected 2.")]
		with (
			patch(
				"joymedia.services.consistency.retention.policy", return_value={"source_hold_pipeline": "P"}
			),
			patch.object(cb.frappe, "get_all", side_effect=[shots, ["TASK"], failed]),
			patch.object(cb, "_start_automatic_scene_repair", return_value=True) as repair,
		):
			self.assertTrue(
				cb._try_source_art_cutaway(frappe._dict(name="CRB"), variants, 0, frappe._dict(name="P"))
			)
		self.assertEqual(1, repair.call_args.kwargs["extra_budget"])
		self.assertEqual([1, 3], [n["scene"] for n in repair.call_args.args[3]])
		self.assertEqual(3, variants[0]["source_art_cutaway_version"])

	def test_the_cutaway_has_one_rewrite_beyond_the_ordinary_budget(self):
		variants = [
			{"status": "Keyframes", "project": "P", "automatic_scene_rewrites": cb.AUTOMATIC_SCENE_REWRITES}
		]
		note = [{"scene": 1, "text": "Remove the pack."}]
		with patch.object(cb, "_write"), patch("frappe.enqueue"), patch("frappe.db.commit"):
			self.assertFalse(cb._start_automatic_scene_repair("CRB", variants, 0, note))
			self.assertTrue(cb._start_automatic_scene_repair("CRB", variants, 0, note, extra_budget=1))

	def test_a_service_outage_during_the_rewrite_keeps_it_queued_for_retry(self):
		from joymedia.services.planning.production import PlannerUnavailableError

		self.assertTrue(cb._service_outage(PlannerUnavailableError("The planner is unavailable")))
		self.assertFalse(cb._service_outage(ValueError("Scene 2 still shows a package.")))


class TestFaceChosenByScript(FrappeTestCase):
	def project(self):
		def row(key, version, label):
			return frappe._dict(
				reference_key=key,
				asset_version=version,
				label=label,
				reference_role="Character",
				identity_key="mascot",
			)

		project = frappe._dict(
			selected_media=[
				frappe._dict(
					reference_key="product",
					asset_version="P",
					reference_role="Product",
					identity_key="product",
				),
				row("mascot_front", "F", "mascot front"),
				row("pose_a", "G1", "seated (verified)"),
				row("pose_b", "G2", "standing (verified)"),
				row("mascot_sheet_view1", "V1", "mascot front"),
				row("mascot_sheet_view3", "V3", "mascot side"),
			],
			save=lambda **kwargs: None,
		)
		project.set = lambda field, value: project.__setitem__(field, value)
		return project

	def choose(self, script):
		project = self.project()
		originals = {"F": "F", "G1": "F", "G2": "F"}
		with patch(
			"joymedia.services.project.reference_lineage.original_reference",
			side_effect=lambda version: {"asset_version": originals.get(version, version)},
		):
			kept = cb._choose_face_for_script(project, script)
		return kept, [row.reference_key for row in project.selected_media], script

	def test_front_scenes_keep_the_family_with_most_verified_poses(self):
		script = {
			"scenes": [{"cast": ["mascot_sheet_view1"], "action": "[0-3s] The mascot lifts the tissue."}]
		}
		kept, keys, script = self.choose(script)
		self.assertEqual(["image:F"], kept)
		self.assertEqual(["product", "mascot_front", "pose_a", "pose_b"], keys)
		self.assertEqual(["mascot_front"], script["scenes"][0]["cast"])

	def test_a_side_view_in_the_script_keeps_the_family_with_side_drawings(self):
		script = {
			"scenes": [
				{"cast": ["mascot_front"], "visual_camera": "Side view of the mascot holding the tissue."}
			]
		}
		kept, keys, script = self.choose(script)
		self.assertEqual(["sheet:mascot_sheet"], kept)
		self.assertEqual(["product", "mascot_sheet_view1", "mascot_sheet_view3"], keys)
		self.assertEqual(["mascot_sheet_view1"], script["scenes"][0]["cast"])

	def test_a_single_face_is_left_unchanged(self):
		project = self.project()
		project.selected_media = project.selected_media[:3]
		with patch(
			"joymedia.services.project.reference_lineage.original_reference",
			side_effect=lambda version: {"asset_version": "F"},
		):
			self.assertEqual([], cb._choose_face_for_script(project, {"scenes": []}))
		self.assertEqual(3, len(project.selected_media))


class TestProductShotsUseTheSourcePhoto(FrappeTestCase):
	def test_automatic_product_only_shots_skip_generation(self):
		shots = [
			frappe._dict(name="S1", consistency_status="", motion_plan_json="{}"),
			frappe._dict(name="S2", consistency_status="", motion_plan_json="{}"),
			frappe._dict(name="S3", consistency_status="", motion_plan_json="{}"),
		]
		sourced = {"S1", "S3"}
		project = frappe._dict(name="P", workflow="W", generation_pipeline="PIPE")
		variant = {}
		with (
			patch.object(cb, "pinned_execution", return_value=nullcontext()),
			patch.object(cb, "delivery_context", return_value=nullcontext()),
			patch("joymedia.services.workflows.capabilities.controls", return_value=set()),
			patch.object(cb.frappe, "get_doc", return_value=frappe._dict()),
			patch.object(cb.frappe, "get_all", return_value=shots),
			patch.object(cb, "is_automatic", return_value=True),
			patch.object(cb, "_use_product_source_for_packshot", return_value=True) as use_source,
			patch.object(cb, "_seal_automatic_plan") as seal,
			patch.object(cb, "_explicit_first_frame", side_effect=lambda name: name in sourced),
			patch("joymedia.services.keyframes.stage.generate_keyframes", return_value={"run": "R"}) as draw,
		):
			cb._submit_visual_stage(project, variant, {"delivery_mode": "automatic"}, "CRB")
		self.assertEqual(3, use_source.call_count)
		seal.assert_called_once_with("P")
		draw.assert_called_once_with("P", ["S2"], draw_places=False)
		self.assertEqual({"run": "R"}, variant["keyframe_request"])
