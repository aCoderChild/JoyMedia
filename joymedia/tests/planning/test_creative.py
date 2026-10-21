import copy
import json
import tempfile
from pathlib import Path
from typing import ClassVar
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning.creative import script_workbook, validate_script
from joymedia.services.planning.grounding import grounded_contract


def sample_script():
	return {
		"title": "A moving product",
		"logline": "A character moves the product, then presents it.",
		"format": "16:9",
		"format_reason": "Room for lateral action",
		"duration_seconds": 10,
		"visual_style": "Warm directional light with layered depth",
		"music": "Bright acoustic percussion, brisk tempo",
		"features": ["Blue exterior"],
		"scenes": [
			{
				"beat_name": "Movement",
				"duration_seconds": 6,
				"visual_camera": "A product on a wooden table.",
				"action": "[0-1s] Grip the product.\n[1-6s] Move it along the table.",
				"visible_change": "Product left -> product right",
				"cast": [],
				"products": ["product"],
				"place": "Warm studio with a wooden table",
				"continuity_rules": "Keep the product supported.",
				"shot_framing": "medium",
				"shot_angle": "eye_level",
				"narrative_stage": "present",
				"voice_over": "",
				"audio_cues": "Soft contact",
				"on_screen_text": "",
			},
			{
				"beat_name": "Resolve",
				"duration_seconds": 4,
				"visual_camera": "Blue product, directional light.",
				"action": "[0-2s] Turn the product to face forward.\n[2-4s] Hold the final view.",
				"visible_change": "Side -> front",
				"cast": [],
				"products": ["product"],
				"place": "Warm studio with a wooden table",
				"continuity_rules": "Preserve its dimensions.",
				"shot_framing": "close_up",
				"shot_angle": "eye_level",
				"narrative_stage": "hero",
				"voice_over": "",
				"audio_cues": "Soft cloth",
				"on_screen_text": "See more",
			},
		],
	}


class TestGeneratedScriptValidation(TestCase):
	inventory: ClassVar = [{"key": "product", "role": "Product"}]
	constraints: ClassVar = {"duration_seconds": 10, "aspect_ratio": "16:9"}

	def test_frame_review_resume_requires_current_native_approval_without_erasing_findings(self):
		from joymedia.services.generation.creative_batch import _keyframe_ready

		shot = frappe._dict(name="shot", consistency_status="Needs Review", keyframe_status="Pending Review")
		self.assertFalse(_keyframe_ready(shot))
		shot.keyframe_status = "Approved"
		with (
			patch("frappe.get_doc", return_value=shot),
			patch("joymedia.services.keyframes.stage.approved_keyframe_task", return_value=None) as approved,
		):
			self.assertFalse(_keyframe_ready(shot))
			approved.return_value = "current-keyframe-task"
			self.assertTrue(_keyframe_ready(shot))
		self.assertEqual("Needs Review", shot.consistency_status)

	def test_omission_retraction_requires_existing_action_text_and_never_qualifies_pixels(self):
		from joymedia.services.planning.script_review import _cross_check_missing_actions

		issue = {
			"scene": 1,
			"category": "missing_contact_or_result",
			"quote": "Grip the product.",
			"instruction": "Show movement.",
		}
		for quote in ("", "Move it along the table.", "Invented result not in the script"):
			with (
				self.subTest(quote=quote),
				patch(
					"joymedia.services.planning.production._ask_planner",
					return_value={"already_written": quote},
				),
			):
				review = {"issues": [copy.deepcopy(issue)]}
				if quote == "Invented result not in the script":
					with self.assertRaisesRegex(ValueError, "absent"):
						_cross_check_missing_actions(review, sample_script())
				else:
					finding = _cross_check_missing_actions(review, sample_script())["issues"][0]
					self.assertEqual(
						"production_detail" if quote else "missing_contact_or_result", finding["category"]
					)
					if quote:
						self.assertFalse(finding["text_cross_check"]["physical_qualification"])

	def test_gallery_views_remain_one_identity_and_can_be_selected_by_scene(self):
		inventory = [
			{
				"key": "front",
				"role": "Product",
				"identity": "one_product",
				"views": [{"key": "front"}, {"key": "back"}],
			}
		]
		script = sample_script()
		for scene in script["scenes"]:
			scene["products"] = ["back"]
		self.assertEqual(
			["back"], validate_script(script, inventory, self.constraints)["scenes"][0]["products"]
		)
		script["scenes"][0]["products"] = ["front", "back"]
		with self.assertRaisesRegex(ValueError, "one view per identity"):
			validate_script(script, inventory, self.constraints)

	def test_generated_timing_reuses_frame_allocation_without_dropping_or_inventing_actions(self):
		from joymedia.services.planning.creative import fit_generated_timing
		from joymedia.services.planning.durations import allocate_frames
		from joymedia.services.planning.timed_actions import read_timed_actions

		script = sample_script()
		script["scenes"][0].update(
			duration_seconds=3, action="[0-0.5s] Grip the product. [0.5-3s] Move it along the table."
		)
		script["scenes"][1].update(duration_seconds=2, action="[0-1s] Turn it. [1-2s] Hold it.")
		compiled = fit_generated_timing(script, 10, 24)
		self.assertEqual([6, 4], [s["duration_seconds"] for s in compiled["scenes"]])
		self.assertEqual(240, sum(compiled["timing_compilation"]["scene_frames"]))
		self.assertEqual(
			["Grip the product.", "Move it along the table."],
			[p["action"] for p in read_timed_actions(compiled["scenes"][0]["action"], 6)],
		)
		self.assertEqual([22, 1, 1], allocate_frames([1000, 0.001, 0.001], 24))
		self.assertEqual(2, len(compiled["scenes"]))

	def test_planner_cache_does_not_reuse_another_configured_models_answer(self):
		from joymedia.services.planning.production import _ask_planner

		with (
			patch(
				"joymedia.services.runtime.endpoints.endpoint",
				side_effect=[
					frappe._dict(model="first", base_url="http://planner/v1"),
					frappe._dict(model="second", base_url="http://planner/v1"),
				],
			),
			patch(
				"joymedia.services.planning.production._request_planner",
				side_effect=[{"from": "first"}, {"from": "second"}],
			) as planner,
			patch("frappe.cache.get_value", return_value=None) as cache_read,
			patch("frappe.cache.set_value"),
		):
			self.assertEqual({"from": "first"}, _ask_planner("same script request"))
			self.assertEqual({"from": "second"}, _ask_planner("same script request"))
		self.assertEqual(2, planner.call_count)
		self.assertNotEqual(cache_read.call_args_list[0].args[0], cache_read.call_args_list[1].args[0])

	def test_second_pass_rejects_missing_scene_evidence(self):
		from joymedia.services.planning.creative import review_script_actions

		with patch(
			"joymedia.services.planning.production._ask_planner", return_value={"findings": []}
		) as planner:
			with self.assertRaisesRegex(ValueError, "each scene"):
				review_script_actions(
					sample_script(),
					[{"key": "mascot-reference", "role": "Character"}],
					[
						{"text": "Maintain real contact", "source": "owner-note", "scope": "Current"},
						{"text": "Earlier rendered failure", "source": "old-note", "scope": "Historical"},
					],
				)
		self.assertIn("mascot-reference", planner.call_args.args[0])
		self.assertIn("Maintain real contact", planner.call_args.args[0])
		self.assertNotIn("Earlier rendered failure", planner.call_args.args[0])

	def test_script_review_accepts_grounded_coverage_and_rejects_invented_issue_evidence(self):
		from joymedia.services.planning.creative import review_script_actions

		good = {
			"coverage": [
				{"scene": 1, "action_quote": "Grip the product."},
				{"scene": 2, "action_quote": "Turn the product to face forward."},
			],
			"issues": [],
		}
		with patch("joymedia.services.planning.production._ask_planner", return_value=good):
			self.assertEqual(good, review_script_actions(sample_script()))
		bad = copy.deepcopy(good)
		bad["issues"] = [
			{
				"scene": 1,
				"category": "unreferenced_actor",
				"quote": "An unreferenced presenter appears.",
				"instruction": "Remove the presenter.",
			}
		]
		with patch("joymedia.services.planning.production._ask_planner", return_value=bad):
			with self.assertRaisesRegex(ValueError, "grounded"):
				review_script_actions(sample_script())

	def test_action_sources_share_bounded_context_in_chronological_order(self):
		from joymedia.services.intake.action_reference import action_observations

		versions = [
			frappe._dict(
				name=name,
				analysis_json=json.dumps(
					{
						"action_reference": {
							"clips": [{"start": i, "end": i + 1, "caption": f"{name}-{i}"} for i in range(6)]
						}
					}
				),
			)
			for name in ("camera", "action")
		]
		with patch("joymedia.services.intake.cinematography.motion_references", return_value=versions):
			observations = action_observations(None)[:8]
		self.assertEqual(["camera", "action"] * 4, [r["source"] for r in observations])
		self.assertEqual([0, 0, 1, 1, 2, 2, 3, 3], [r["start"] for r in observations])

	def test_script_repair_preserves_all_prior_errors_and_uses_script_system(self):
		from joymedia.services.planning.creative import draft_script

		bad_count = sample_script()
		bad_count["scenes"] = bad_count["scenes"][:1]
		bad_enum = sample_script()
		bad_enum["scenes"][0]["shot_framing"] = "Medium"
		project = frappe._dict(total_duration_seconds=10, delivery_width=1280, delivery_height=720)
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"identity": "internal-id",
				"label": "Label",
				"keep_rule": "Keep the original connected proportions.",
				"views": [{"description": "Blue product"}],
			}
		]
		with (
			patch("joymedia.services.planning.creative.reference_inventory", return_value=inventory),
			patch("joymedia.services.intake.action_reference.action_observations", return_value=[]),
			patch("joymedia.services.intake.references.brand", return_value={}),
			patch(
				"joymedia.services.planning.creative.review_script_actions",
				return_value={"coverage": [], "issues": []},
			),
			patch(
				"joymedia.services.planning.production._ask_planner",
				side_effect=[bad_count, bad_enum, sample_script()],
			) as planner,
		):
			expected = sample_script()
			expected["action_review"] = {"coverage": [], "issues": []}
			actual = draft_script(
				project,
				nonce="varied",
				review_notes=[{"source": "old-note", "text": "Prior version observation."}],
			)
			actual.pop("timing_compilation")
			self.assertEqual(expected, actual)
		last = planner.call_args
		self.assertIn("2–12 scenes", last.args[0])
		self.assertIn("Unsupported shot_framing", last.args[0])
		self.assertNotIn('"identity": "internal-id"', last.args[0])
		self.assertIn("Keep the original connected proportions.", last.args[0])
		self.assertIn('"scope": "Historical"', last.args[0])
		self.assertIn("multi-scene", last.kwargs["system"])
		self.assertEqual("writer", last.kwargs["capability"])
		self.assertIn("scenes", last.kwargs["response_schema"]["properties"])

	def test_production_detail_reaches_planning_but_missing_prerequisite_still_blocks(self):
		from joymedia.services.planning.creative import draft_script

		project = frappe._dict(total_duration_seconds=10, delivery_width=1280, delivery_height=720)
		inventory = [
			{
				"key": "product",
				"role": "Product",
				"identity": "product",
				"label": "Product",
				"views": [{"description": "Blue product"}],
			}
		]
		instruction = "Maintain supported contact throughout the movement."
		for category in ("production_detail", "missing_prerequisite"):
			with (
				patch("joymedia.services.planning.creative.reference_inventory", return_value=inventory),
				patch("joymedia.services.intake.action_reference.action_observations", return_value=[]),
				patch("joymedia.services.intake.references.brand", return_value={}),
				patch(
					"joymedia.services.planning.production._ask_planner",
					side_effect=lambda *a, **k: copy.deepcopy(sample_script()),
				) as writer,
				patch(
					"joymedia.services.planning.creative.review_script_actions",
					return_value={
						"coverage": [],
						"issues": [
							{
								"scene": 1,
								"category": category,
								"quote": "Move it along the table.",
								"instruction": instruction,
							}
						],
					},
				),
			):
				if category == "production_detail":
					self.assertIn(
						instruction,
						draft_script(project, nonce="production-note")["scenes"][0]["continuity_rules"],
					)
				else:
					with self.assertRaisesRegex(ValueError, "missing_prerequisite"):
						draft_script(project, nonce="blocking-note")
					self.assertIn("LATEST SCREENPLAY:", writer.call_args.args[0])
					self.assertIn(sample_script()["scenes"][0]["visual_camera"], writer.call_args.args[0])
					self.assertEqual("creative_script_repair", writer.call_args.kwargs["sampling_profile"])

	def test_authored_geometry_timing_and_cast_remain_authoritative(self):
		self.assertEqual(sample_script(), validate_script(sample_script(), self.inventory, self.constraints))
		for mutate in (
			lambda s: s.update(format="9:16"),
			lambda s: s.update(duration_seconds=30),
			lambda s: s.update(duration_seconds=float("nan")),
			lambda s: s["scenes"][0].update(cast=["invented_actor"]),
			lambda s: s["scenes"][0].update(action="The camera moves slowly."),
			lambda s: s["scenes"][0].update(action="[0-1s] Grip.\n[2-6s] Move."),
			lambda s: s["scenes"][0].update(duration_seconds=float("nan")),
		):
			script = sample_script()
			mutate(script)
			with self.subTest(script=script), self.assertRaises(ValueError):
				validate_script(script, self.inventory, self.constraints)

	def test_physical_props_require_exact_authored_evidence_and_cannot_replace_actors(self):
		base = {
			"version": 1,
			"entities": [{"id": "actor", "label": "the supplied actor"}],
			"relations": [],
			"checks": [],
			"events": [{"id": "action1", "description": "Move", "start": 0, "end": 1, "after": []}],
		}
		inferred = {
			"additional_entities": [{"id": "support", "source_quote": "wooden table", "kind": "support"}],
			"relations": [{"kind": "supported_by", "subject": "actor", "object": "support"}],
			"events": [{"id": "invented"}],
		}
		result = grounded_contract(base, inferred, "The actor acts on a wooden table.")
		self.assertEqual(base["events"], result["events"])
		self.assertEqual("wooden table", result["entities"][-1]["label"])
		for field, value in (("source_quote", "chair"), ("kind", "actor"), ("id", "actor")):
			bad = copy.deepcopy(inferred)
			bad["additional_entities"][0][field] = value
			with self.subTest(field=field), self.assertRaises(ValueError):
				grounded_contract(base, bad, "The actor acts on a wooden table.")

	def test_inferred_reveal_uses_available_tracking_without_changing_explicit_controls(self):
		from joymedia.services.planning.camera import (
			camera_plan,
			executable_inferred_intent,
			infer_cinematic_intent,
		)

		structure = {
			"stage": "establish",
			"framing": "wide",
			"angle": "eye_level",
			"subject_motion": "locomotion",
			"keep_visible": [],
		}
		preferred = {"behavior": "arc", "allow_reframe": True, "purpose": "hook", "energy": "brisk"}
		resolved = executable_inferred_intent(preferred, structure, set())
		self.assertEqual("tracking_backward", resolved["behavior"])
		self.assertEqual("arc", preferred["behavior"])
		# A coarse extraction label must not lock a genuinely travelling subject
		# out of frame; explicit camera_motion=locked remains authoritative below.
		self.assertEqual(
			"tracking_backward", infer_cinematic_intent(dict(structure, stage="extract"))["behavior"]
		)
		shot = {
			"shot_number": 1,
			"motion_plan_json": {"shot_structure": structure, "camera_intent": resolved},
		}
		self.assertEqual("tracking_backward", camera_plan(shot, {})["behavior"])
		shot["motion_plan_json"]["camera_motion"] = "locked"
		self.assertEqual("locked", camera_plan(shot, {})["behavior"])

	def test_actual_frozen_keyframe_supplies_framing_evidence_without_manual_upload(self):
		from types import SimpleNamespace

		from PIL import Image

		from joymedia.services.planning.framing import inspect_framing

		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "keyframe.png"
			Image.new("RGB", (200, 400), "white").save(path)
			artifact = SimpleNamespace(name="frozen-artifact", frappe_file="/private/files/keyframe.png")
			with (
				patch(
					"frappe.get_doc",
					side_effect=lambda kind, *args: artifact
					if kind == "Generation Artifact"
					else SimpleNamespace(get_full_path=lambda: str(path)),
				),
				patch(
					"frappe.get_site_path",
					side_effect=lambda *args: str(Path(directory) / "cache" / args[-1]),
				),
				patch("joymedia.services.runtime.endpoints.is_configured", return_value=True),
				patch(
					"joymedia.services.runtime.endpoints.endpoint", return_value=frappe._dict(model="vision")
				),
				patch(
					"joymedia.services.review.consistency.ask",
					return_value={"bbox_2d": [20, 40, 180, 360], "complete": True},
				),
			):
				report = inspect_framing({"references": [], "keyframe_artifact": artifact.name})
				self.assertEqual("assessed", report["status"])
				self.assertEqual(artifact.name, report["generation_artifact"])
				self.assertEqual([0.1, 0.1, 0.9, 0.9], report["bounds"])


class TestCreativeWorkflow(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		self.project = frappe.get_doc(
			{
				"doctype": "Media Project",
				"project_name": "Reference-only test",
				"product_name": "Blue product",
				"total_duration_seconds": 10,
				"delivery_width": 1280,
				"delivery_height": 720,
				"delivery_preset": "Landscape",
			}
		).insert(ignore_permissions=True)
		from joymedia.services.intake.assets import create_media_asset
		from joymedia.tests.support.e2e_setup import _generate_image_bytes

		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "product-view.png",
				"content": _generate_image_bytes(),
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		created = create_media_asset("Blue product", "Product", file_name=file.name)
		self.version = created["asset_version"]
		frappe.db.set_value(
			"Asset Version",
			self.version,
			{
				"analysis_status": "Ready",
				"analysis_json": json.dumps(
					{"version": 2, "kind": "product", "description": "A blue product."}
				),
			},
		)
		self.project.append(
			"selected_media",
			{
				"reference_key": "product",
				"identity_key": "one_product",
				"reference_role": "Product",
				"asset_version": self.version,
				"label": "Blue product",
			},
		)
		self.project.save(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def batch(self, count=1):
		from joymedia.api.creative import create_product_batch

		with patch("frappe.enqueue"):
			result = create_product_batch(self.project.name, count=count, auto_render=False)
		return frappe.get_doc("Creative Batch", result["batch"])

	def test_batch_count_is_independent_of_photo_count_and_preserves_format(self):
		batch = self.batch(20)
		request = frappe.parse_json(batch.request_json)
		self.assertEqual(20, len(frappe.parse_json(batch.variants_json)))
		self.assertEqual(1, len(request["references"]))
		self.assertEqual((1280, 720, 10), (request["width"], request["height"], request["duration_seconds"]))
		self.assertEqual(20, len({v["nonce"] for v in frappe.parse_json(batch.variants_json)}))
		for count in (0, 21, True, "many"):
			with self.subTest(count=count), self.assertRaises(ValueError):
				self.batch(count)

	def test_automatic_request_freezes_existing_owner_feedback(self):
		note = {"source": "owner-feedback", "category": "Physics", "text": "Maintain visible tool contact."}
		with patch("joymedia.api.creative._review_context", return_value=[note]):
			batch = self.batch()
		self.assertEqual([note], frappe.parse_json(batch.request_json)["review_notes"])

	def test_generated_workbook_round_trips_through_the_existing_import_schema(self):
		from joymedia.services.planning.workbook import read_workbook

		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "generated.xlsx"
			path.write_bytes(script_workbook(sample_script(), self.project))
			parsed = read_workbook(path)
		demo = parsed["demos"][0]
		self.assertEqual("16:9", demo["metadata"]["format"])
		self.assertEqual([6, 4], [s["duration_seconds"] for s in demo["scenes"]])
		self.assertEqual(sample_script()["scenes"][0]["action"], demo["scenes"][0]["action"])
		self.assertEqual("medium", demo["scenes"][0]["shot_framing"])
		self.assertFalse(demo["scenes"][0].get("narrative_stage"))
		self.assertEqual("cinematic", parsed["brand"]["camera_style"])
		self.assertIn(sample_script()["scenes"][0]["visible_change"], demo["scenes"][0]["continuity"])
		self.assertEqual([], demo["timing_warnings"])

	def test_generated_fractional_frame_timing_round_trips_without_gaps_or_lost_phases(self):
		from joymedia.services.planning.creative import fit_generated_timing
		from joymedia.services.planning.timed_actions import read_timed_actions
		from joymedia.services.planning.workbook import read_workbook

		script = sample_script()
		script["scenes"] = [copy.deepcopy(script["scenes"][0]) for _ in range(7)]
		script = fit_generated_timing(script, 30, 24)
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "frame-script.xlsx"
			path.write_bytes(script_workbook(script, self.project))
			demo = read_workbook(path)["demos"][0]
		self.assertEqual([], demo["timing_warnings"])
		self.assertAlmostEqual(30, sum(s["duration_seconds"] for s in demo["scenes"]))
		self.assertEqual(720, sum(round(s["duration_seconds"] * 24) for s in demo["scenes"]))
		for scene in demo["scenes"]:
			self.assertEqual(2, len(read_timed_actions(scene["action"], scene["duration_seconds"])))

	def test_cancellation_is_durable_and_concurrent_variant_writes_do_not_erase_progress(self):
		from joymedia.services.generation.creative_batch import _write

		batch = self.batch(2)
		first = frappe.parse_json(batch.variants_json)
		stale = copy.deepcopy(first)
		first[0]["status"] = "Script Ready"
		_write(batch.name, first, changed_index=0)
		stale[1]["status"] = "Script Ready"
		_write(batch.name, stale, changed_index=1)
		batch.reload()
		self.assertEqual("Scripts Ready", batch.status)
		self.assertEqual(
			["Script Ready", "Script Ready"], [v["status"] for v in frappe.parse_json(batch.variants_json)]
		)
		batch.db_set("status", "Cancelled")
		self.assertFalse(_write(batch.name, first, "Planning", changed_index=0))
		self.assertEqual("Cancelled", batch.reload().status)

	def test_automatic_render_does_not_override_failed_keyframe_review(self):
		from joymedia.services.generation.creative_batch import advance_batch
		from joymedia.tests.editing.test_timeline import _create_workflow

		self.project.db_set("workflow", _create_workflow())

		batch = self.batch()
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Keyframes")
		batch.db_set({"status": "Rendering", "variants_json": frappe.as_json([variant])})
		shot = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": self.project.name,
				"shot_number": 1,
				"duration_seconds": 10,
				"generation_prompt": "Act.",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Shot",
			shot.name,
			{
				"keyframe_artifact": "unqualified-reference",
				"consistency_status": "Needs Review",
				"consistency_notes": "Unsupported seated geometry",
			},
		)
		with (
			patch("joymedia.services.keyframes.stage.set_keyframe_approval") as approve,
			patch.object(frappe.db, "rollback"),
		):
			advance_batch(batch.name)
			approve.assert_not_called()
		self.assertEqual("Needs Attention", batch.reload().status)
		self.assertIn("Unsupported seated geometry", frappe.parse_json(batch.variants_json)[0]["error"])

	def test_retry_resumes_failed_stage_without_erasing_evidence_or_cancel_state(self):
		from joymedia.api.creative import retry_product_variant

		batch = self.batch()
		variants = frappe.parse_json(batch.variants_json)
		variants[0].update(
			status="Needs Attention",
			resume_stage="Keyframes",
			keyframe_request={"run": "original-run"},
			error="Check geometry",
		)
		batch.db_set({"status": "Needs Attention", "variants_json": frappe.as_json(variants)})
		with patch("frappe.enqueue") as enqueue:
			result = retry_product_variant(batch.name, 1)
		self.assertEqual("Keyframes", result["status"])
		self.assertIn("advance_batch", enqueue.call_args.args[0])
		self.assertEqual(f"joymedia-creative-advance:{batch.name}", enqueue.call_args.kwargs["job_id"])
		updated = frappe.parse_json(batch.reload().variants_json)[0]
		self.assertEqual({"run": "original-run"}, updated["keyframe_request"])
		batch.db_set("status", "Cancelled")
		with self.assertRaisesRegex(ValueError, "cancelled"):
			retry_product_variant(batch.name, 1)

	def test_guest_cannot_read_batch_or_create_from_another_users_project(self):
		from joymedia.api.creative import create_product_batch, get_product_batch

		batch = self.batch()
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_product_batch(batch.name)
			with self.assertRaises(frappe.PermissionError):
				create_product_batch(self.project.name)
		finally:
			frappe.set_user("Administrator")

	def test_finishing_queues_a_fresh_review_export_instead_of_reusing_an_old_output(self):
		from joymedia.services.generation.creative_batch import advance_batch

		batch = self.batch()
		variant = frappe.parse_json(batch.variants_json)[0]
		variant.update(project=self.project.name, status="Finishing")
		batch.db_set({"status": "Finishing", "variants_json": frappe.as_json([variant])})
		self.project.db_set(
			{"post_production_status": "Completed", "current_output_asset_version": self.version}
		)
		with patch("joymedia.services.editing.export_jobs.queue_project_timeline_export") as export:
			advance_batch(batch.name)
			export.assert_called_once_with(self.project.name, purpose="review")
		self.assertEqual("Exporting", frappe.parse_json(batch.reload().variants_json)[0]["status"])
