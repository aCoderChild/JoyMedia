import io
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from joymedia.services.keyframes import locations


def _shot(name, setting, environment=None, camera="Wide shot."):
	shot = frappe._dict(
		name=name,
		setting_prompt=setting,
		generation_inputs=[],
		generation_prompt=f"The kid plays. Camera: {camera}",
	)
	if environment:
		shot.generation_inputs.append(
			frappe._dict(name=f"{name}-env", reference_role="Environment", asset_version=environment)
		)
	added = []

	def append(field, row):
		row = frappe._dict(row, db_insert=MagicMock())
		shot.generation_inputs.append(row)
		added.append(row)
		return row

	shot.append, shot.added = append, added
	return shot


class TestLocationPlates(FrappeTestCase):
	def test_plain_studio_cannot_pass_as_a_furnished_room(self):
		for answer in (
			{"answer": False, "reason": "Sofas and a table replace the neutral studio."},
			{"answer": True, "reason": ""},
		):
			with patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[{"answer": False}, {"answer": False}, answer],
			):
				self.assertFalse(locations._location_supports_staging(b"room", "Plain grey studio", ""))
		self.assertNotIn("complete furnished location", locations.LOCATION_PLATE)
		self.assertEqual(
			"Neutral source-photo setting",
			locations._architectural_setting("Neutral source-photo setting with no actor or loose paper."),
		)
		self.assertEqual(
			locations.location_key("Neutral source-photo setting"),
			locations.location_key("Neutral source-photo setting with no actor or loose paper."),
		)

	def test_floor_story_does_not_reuse_a_tabletop_plate_or_parse_boilerplate_as_furniture(self):
		import json

		shot = frappe._dict(
			setting_prompt="Cozy living room",
			image_prompt="The mascot sits on a cozy rug. Product orientation is locked. Its table or floor is visible.",
		)
		staging = locations._location_staging(shot)
		self.assertIn("floor work area", staging)
		self.assertNotIn("working table", staging)
		source = {
			"selected_demo": {
				"scenes": [
					{
						"place": "Cozy living room",
						"camera": "The mascot sits on a cozy rug.",
						"action": "Extract a tissue from the supported pack.",
					}
				]
			}
		}
		project = frappe._dict(
			storyboard_source_json=json.dumps(source),
			selected_media=[
				frappe._dict(
					reference_key=locations.location_key("Cozy living room"),
					label="Location 1: Cozy living room",
				)
			],
		)
		self.assertTrue(locations.place_key(project, "Cozy living room").startswith("location_floor_"))
		source["selected_demo"]["scenes"][0]["camera"] += " Beside a working table."
		project.storyboard_source_json = json.dumps(source)
		self.assertEqual(
			locations.location_key("Cozy living room"), locations.place_key(project, "Cozy living room")
		)

	def test_floor_location_rejects_a_table_occupying_its_action_space(self):
		with patch(
			"joymedia.services.review.consistency.ask",
			side_effect=[{"answer": False}, {"answer": False}, {"answer": False}],
		):
			self.assertFalse(
				locations._location_supports_staging(
					b"plate", "living room", "clear foreground floor work area"
				)
			)

	def test_separate_location_fit_checks_require_all_three_and_no_negative_summary(self):
		for fit, expected in [
			({"scale": True, "visual_fit": True, "placement": True}, True),
			({"scale": True, "visual_fit": True}, False),
			({"scale": True, "visual_fit": True, "placement": False}, False),
			({"answer": False, "scale": True, "visual_fit": True, "placement": True}, False),
		]:
			with (
				self.subTest(fit=fit),
				patch(
					"joymedia.services.review.consistency.ask",
					side_effect=[
						{"answer": False},
						{"answer": False},
						{"bbox": [100, 300, 800, 600]},
						{"answer": False},
						{"answer": True},
						{"answer": True},
						fit,
						{"answer": True, "reason": "Requested living room and its furniture are visible."},
						{"answer": True},
					],
				),
				patch.object(locations, "_tabletop_crop", return_value=b"crop"),
			):
				self.assertEqual(
					expected, locations._location_supports_staging(b"image", "living room", "working table")
				)

	def test_tabletop_pixel_box_uses_the_sent_thumbnail_dimensions(self):
		buffer = io.BytesIO()
		image = Image.new("RGB", (1200, 1600), "red")
		image.paste("blue", (0, 800, 1200, 1600))
		image.save(buffer, "PNG")
		crop = locations._tabletop_crop(buffer.getvalue(), [0, 512, 768, 1024], pixel_edge=1024)
		with Image.open(io.BytesIO(crop)) as result:
			self.assertEqual((1200, 896), result.size)
			self.assertEqual((0, 0, 255), result.getpixel((600, 448)))

	def test_failed_place_does_not_start_first_frames(self):
		with (
			patch.object(locations, "draw_project_places", side_effect=ValueError("no verified table")),
			patch("joymedia.services.keyframes.stage.generate_keyframes") as frames,
		):
			with self.assertRaisesRegex(ValueError, "no verified table"):
				locations.draw_places_then_frames("PRJ-X", ["SHOT-X"], "test@example.com")
		frames.assert_not_called()

	def test_ambiguous_action_support_is_rejected(self):
		with patch(
			"joymedia.services.review.consistency.ask",
			side_effect=[{"answer": False}, {"answer": False}, {"answer": None}],
		):
			self.assertFalse(locations._location_supports_staging(b"image", "studio", "clear floor"))

	def test_prefers_better_proportioned_location_plate(self):
		with patch("joymedia.services.review.consistency.ask", return_value={"better": 2}) as observer:
			self.assertEqual(
				locations._prefer_location_plate(
					[b"oversized", b"proportionate"], "living room", "working table"
				),
				b"proportionate",
			)
			self.assertEqual(observer.call_args.args[0], [b"oversized", b"proportionate"])
			self.assertIn("material, finish, and design", observer.call_args.args[1])
			self.assertIn("location, perspective, and reach", observer.call_args.args[1])

	def test_location_comparison_keeps_first_when_ambiguous(self):
		with patch("joymedia.services.review.consistency.ask", return_value={"better": None}):
			self.assertEqual(
				locations._prefer_location_plate([b"first", b"second"], "living room", "working table"),
				b"first",
			)

	def test_living_room_rejects_a_table_that_does_not_fit_the_seating(self):
		with (
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"answer": False},  # no actor
					{"answer": False},  # bare surface
					{"bbox": [200, 400, 800, 600]},  # tabletop bounds
					{"answer": False},  # bare cropped tabletop
					{"answer": True},  # structurally valid table
					{"answer": True},  # sofa is present
					{"answer": False},  # table is dining height beside sofa
				],
			) as observer,
			patch.object(locations, "_tabletop_crop", return_value=b"crop"),
		):
			self.assertFalse(
				locations._location_supports_staging(
					b"image", "A cozy living room with a sofa", "reachable working table"
				)
			)
			self.assertIn("low coffee table", observer.call_args_list[-1].args[1])
			self.assertIn("material, finish and design", observer.call_args_list[-1].args[1])

	def test_tabletop_crop_rejects_invalid_geometry(self):
		buffer = io.BytesIO()
		Image.new("RGB", (400, 600), "white").save(buffer, "PNG")
		self.assertIsNone(locations._tabletop_crop(buffer.getvalue(), [800, 100, 200, 300]))
		self.assertIsNone(locations._tabletop_crop(buffer.getvalue(), [100, 100, 102, 102]))
		crop = locations._tabletop_crop(buffer.getvalue(), [100, 300, 900, 650])
		self.assertIsNotNone(crop)
		with Image.open(io.BytesIO(crop)) as image:
			self.assertLess(image.width, 400)

	def test_rejects_tabletop_with_books_even_if_full_image_check_missed_them(self):
		with (
			patch(
				"joymedia.services.review.consistency.ask",
				side_effect=[
					{"answer": False},
					{"answer": False},
					{"bbox": [150, 400, 850, 700]},
					{"answer": True, "objects": ["books"]},
				],
			) as observer,
			patch.object(locations, "_tabletop_crop", return_value=b"crop"),
		):
			self.assertFalse(
				locations._location_supports_staging(b"image", "living room", "reachable working table")
			)
			self.assertEqual(observer.call_args.args[0], b"crop")

	def test_living_room_table_requires_observer_evidence(self):
		with patch("joymedia.services.review.consistency.ask", side_effect=RuntimeError("offline")):
			self.assertFalse(
				locations._location_supports_staging(
					b"image", "A cozy living room", "reachable working table"
				)
			)

	def test_location_plate_rejects_any_embedded_cast_or_product(self):
		with patch("joymedia.services.review.consistency.ask", return_value={"answer": True}) as observer:
			self.assertFalse(locations._location_supports_staging(b"image", "living room", "table"))
			self.assertEqual(1, observer.call_count)

	def test_location_staging_uses_architecture_before_actor_action(self):
		shot = frappe._dict(
			image_prompt="A wide shot of a lived-in room with a table and chair. The mascot holds a branded pack."
		)
		self.assertEqual(
			"reachable working table, physically usable seat",
			locations._location_staging(shot),
		)
		self.assertNotIn(
			"cup", locations._location_staging(frappe._dict(image_prompt="A cup spills onto a table."))
		)

	def test_mixed_setting_drops_actor_and_product_clause_but_keeps_room(self):
		self.assertEqual(
			"Cozy living room with a table",
			locations._architectural_setting("Cozy living room with a table and the mascot seated."),
		)

	def test_location_plate_rejects_missing_action_support(self):
		with patch(
			"joymedia.services.review.consistency.ask",
			side_effect=[{"answer": False}, {"answer": False}, {"answer": False}],
		):
			self.assertFalse(
				locations._location_supports_staging(
					b"image", "lived-in room", "Bear sits by a reachable table and chair."
				)
			)

	def test_environment_render_uses_the_same_pinned_pipeline_as_its_project(self):
		with (
			patch(
				"joymedia.services.workflows.pipeline.get_pinned_generation_pipeline",
				return_value=frappe._dict(name="PINNED"),
			) as pinned,
			patch("joymedia.services.workflows.pipeline.get_active_generation_pipeline") as active,
			patch(
				"joymedia.services.workflows.pipeline.get_pipeline_steps",
				return_value=[frappe._dict(workflow="IMAGE")],
			) as steps,
			patch.object(
				frappe, "get_doc", return_value=frappe._dict(output_media_type="Image", name="IMAGE")
			),
		):
			self.assertEqual("IMAGE", locations._keyframe_workflow(frappe._dict(name="PROJECT")).name)
		pinned.assert_called_once_with("PROJECT")
		active.assert_not_called()
		steps.assert_called_once_with("PINNED")

	def test_scenes_with_the_same_setting_share_one_place(self):
		key = locations.location_key
		self.assertEqual(key("Warm, cozy family dining room."), key("  warm, cozy  family dining room. "))
		self.assertNotEqual(key("Warm, cozy family dining room."), key("A bright bathroom."))
		# A scene that names no place uses the default setting, and all such scenes share it.
		self.assertEqual(key(""), key(None))

	def test_synonymous_settings_in_one_batch_need_only_one_plate(self):
		project = frappe._dict(selected_media=[])
		shots = [
			_shot("S1", "Lived-in room with a table and chair."),
			_shot("S2", "Same lived-in room."),
		]
		self.assertEqual(1, len(locations.missing_places(project, shots)))

	def test_each_missing_place_is_drawn_once_and_a_scene_with_its_own_environment_is_left_alone(self):
		project = frappe._dict(
			selected_media=[
				frappe._dict(reference_key=locations.location_key("A bathroom.")),
				frappe._dict(reference_key="garden", asset_version="ASTV-CLIENT"),
			]
		)
		shots = [
			_shot("S1", "A dining room."),
			_shot("S2", "A dining room."),
			_shot("S3", "A bathroom."),
			_shot("S4", "A garden.", environment="ASTV-CLIENT"),
			_shot("S5", "A kitchen.", camera="Close-up of the cup."),
		]
		# A place seen only in close-ups is drawn too: its close view is cut from it.
		self.assertEqual(
			{
				locations.location_key("A dining room."): "A dining room.",
				locations.location_key("A kitchen."): "A kitchen.",
			},
			locations.missing_places(project, shots),
		)

	def test_one_supplied_environment_anchors_room_and_table_views(self):
		project = frappe._dict(
			name="PRJ-X",
			selected_media=[
				frappe._dict(
					reference_key="supplied_room",
					reference_role="Environment",
					asset_version="ASTV-CLIENT-ROOM",
				)
			],
		)
		shots = [_shot("S1", "Room with a table and sofa."), _shot("S2", "Table with the pack.")]
		self.assertEqual({}, locations.missing_places(project, shots))
		with patch("joymedia.services.review.comments._reseal_approved_plan"):
			self.assertEqual(2, locations.assign_places(project, shots))
		self.assertEqual(
			["ASTV-CLIENT-ROOM", "ASTV-CLIENT-ROOM"],
			[s.generation_inputs[0].asset_version for s in shots],
		)

	def test_only_a_scene_that_shows_the_room_gets_the_place(self):
		def shows(camera):
			return locations.shows_the_room(_shot("S", "A room.", camera=camera))

		# Authored close-up framing stays close; it does not show the whole room.
		for camera in (
			"Wide shot.",
			"Medium shot, front view.",
			"Wide shot to close-up.",
			"Eye-level.",
		):
			self.assertTrue(shows(camera), camera)
		for camera in (
			"Close-up of family dining table.",
			"Top-down (overhead)",
			"Close-up, side angle",
			"Extreme close-up of the pack.",
		):
			self.assertFalse(shows(camera), camera)
		self.assertTrue(locations.shows_the_room(frappe._dict(generation_prompt="The kid plays.")))

	def test_structured_medium_and_details_receive_closer_location_context(self):
		for framing in ("wide", "medium", "close_up", "extreme_close_up"):
			shot = frappe._dict(
				motion_plan_json={
					"shot_structure": {
						"stage": "present",
						"framing": framing,
						"angle": "eye_level",
						"subject_motion": "stationary",
						"keep_visible": [],
					},
					"scene_contract": {"entities": []},
				}
			)
			self.assertEqual(framing == "wide", locations.shows_the_room(shot))

	def test_each_scene_gets_the_picture_of_its_place(self):
		room = locations.location_key("A dining room.")
		project = frappe._dict(
			name="PRJ-X",
			selected_media=[
				frappe._dict(reference_key=room, asset_version="ASTV-ROOM"),
				frappe._dict(reference_key=room + locations.CLOSE, asset_version="ASTV-ROOM-CLOSE"),
				frappe._dict(reference_key="pack", asset_version="ASTV-PACK"),
				frappe._dict(reference_key="garden", asset_version="ASTV-CLIENT"),
			],
		)
		shots = [
			_shot("S1", "A dining room."),
			_shot("S2", "A dining room."),
			_shot("S3", "A garden.", environment="ASTV-CLIENT"),
			# A close-up that was given the whole room before gets the close view of it instead.
			_shot("S4", "A dining room.", environment="ASTV-ROOM", camera="Close-up of the cup."),
		]
		with (
			patch("joymedia.services.review.comments._reseal_approved_plan") as reseal,
			patch("frappe.db.delete") as delete,
		):
			self.assertEqual(3, locations.assign_places(project, shots))
		self.assertEqual(["ASTV-ROOM"], [row.asset_version for row in shots[0].added])
		self.assertEqual("Environment", shots[1].added[0].reference_role)
		self.assertEqual([], shots[2].added)
		self.assertEqual(["ASTV-ROOM-CLOSE"], [row.asset_version for row in shots[3].generation_inputs])
		delete.assert_called_once_with("Shot Reference", {"name": "S4-env"})
		shots[0].added[0].db_insert.assert_called_once()
		reseal.assert_called_once_with("PRJ-X")
		# Drawn once: assigning again changes nothing.
		with patch("joymedia.services.review.comments._reseal_approved_plan") as reseal:
			self.assertEqual(0, locations.assign_places(project, shots))
		reseal.assert_not_called()

	def test_free_composition_keeps_uncropped_setting_and_support_surfaces_for_detail_shots(self):
		key = locations.location_key("A dining room.")
		project = frappe._dict(
			name="P",
			workflow="FREE",
			selected_media=[
				frappe._dict(reference_key=key, asset_version="ROOM"),
				frappe._dict(reference_key=key + locations.CLOSE, asset_version="CROP"),
			],
		)
		shot = _shot("S", "A dining room.", environment="CROP", camera="Close-up of the product.")
		with (
			patch(
				"frappe.get_doc",
				return_value=frappe._dict(execution_spec={"capabilities": ["reference_only"]}),
			),
			patch("frappe.db.delete"),
			patch("joymedia.services.review.comments._reseal_approved_plan"),
			patch.object(locations, "_ensure_close_views") as crop,
		):
			self.assertEqual(1, locations.assign_places(project, [shot]))
			crop.assert_not_called()
		self.assertEqual(["ROOM"], [row.asset_version for row in shot.generation_inputs])

	def test_reference_composed_image_stage_keeps_floor_and_support_context(self):
		key = locations.location_key("A dining room.")
		project = frappe._dict(
			name="P",
			generation_pipeline="PIPE",
			selected_media=[
				frappe._dict(reference_key=key, asset_version="ROOM"),
				frappe._dict(reference_key=key + locations.CLOSE, asset_version="CROP"),
			],
		)
		shot = _shot("S", "A dining room.", environment="CROP", camera="Close-up of the product.")
		with (
			patch(
				"joymedia.services.workflows.pipeline.get_pipeline_steps",
				return_value=[frappe._dict(workflow="IMAGE")],
			),
			patch(
				"frappe.get_doc",
				return_value=frappe._dict(
					output_media_type="Image", execution_spec={"capabilities": ["free_composition"]}
				),
			),
			patch("frappe.db.delete"),
			patch("joymedia.services.review.comments._reseal_approved_plan"),
			patch.object(locations, "_ensure_close_views") as crop,
		):
			self.assertEqual(1, locations.assign_places(project, [shot]))
			crop.assert_not_called()
		self.assertEqual(["ROOM"], [row.asset_version for row in shot.generation_inputs])

	def test_a_missing_place_is_drawn_in_the_background_before_the_frames(self):
		from joymedia.services.keyframes import stage

		project = frappe._dict(name="PRJ-X", storyboard_approval_status="Approved", selected_media=[])
		shot = _shot("S1", "A dining room.")
		with (
			patch.object(stage, "_project_and_shots", return_value=(project, [shot])),
			patch("joymedia.services.generation.takes._ensure_scene_free"),
			patch("joymedia.services.generation.takes._start_takes_run") as start,
			patch("frappe.enqueue") as enqueue,
		):
			self.assertEqual({"status": "Drawing places"}, stage.generate_keyframes("PRJ-X"))
		start.assert_not_called()
		self.assertEqual(
			"joymedia.services.keyframes.locations.draw_places_then_frames", enqueue.call_args.args[0]
		)
		self.assertEqual(["S1"], enqueue.call_args.kwargs["shot_names"])

	def test_the_close_view_is_the_middle_of_the_room_at_the_frames_size(self):
		import io

		from PIL import Image

		picture = Image.new("RGB", (720, 1280), "white")
		picture.paste((200, 0, 0), (300, 700, 420, 900))  # a red table in the middle of the floor
		buffer = io.BytesIO()
		picture.save(buffer, "PNG")
		view = Image.open(io.BytesIO(locations.close_view(buffer.getvalue())))
		self.assertEqual((720, 1280), view.size)
		red = sum(1 for pixel in view.getdata() if pixel[0] > 150 and pixel[1] < 60)
		self.assertGreater(
			red / (720 * 1280), 3 * (120 * 200) / (720 * 1280)
		)  # the table fills more of the frame


class TestSplitScreenViews(FrappeTestCase):
	ROOM = "Warm, cozy family dining room with traditional wooden table."

	def test_a_view_of_the_films_own_room_uses_its_close_view_and_other_views_their_own_picture(self):
		self.assertTrue(locations.same_place("Family dining table", self.ROOM))
		self.assertFalse(locations.same_place("On a picnic mat outdoors", self.ROOM))
		project = frappe._dict(selected_media=[])
		self.assertEqual(
			locations.location_key(self.ROOM) + locations.CLOSE,
			locations.view_key(project, "Family dining table", self.ROOM),
		)
		self.assertEqual(
			locations.location_key("Inside a handbag"),
			locations.view_key(project, "Inside a handbag", self.ROOM),
		)

	def test_only_views_without_a_picture_are_drawn(self):
		import json

		views = [
			{"text": "Family dining table"},
			{"text": "On a picnic mat outdoors"},
			{"text": "Inside a handbag"},
		]
		shot = frappe._dict(setting_prompt=self.ROOM, views_json=json.dumps(views), generation_inputs=[])
		project = frappe._dict(
			selected_media=[frappe._dict(reference_key=locations.location_key("Inside a handbag"))]
		)
		self.assertEqual(
			{locations.location_key("On a picnic mat outdoors"): "On a picnic mat outdoors"},
			locations.missing_views(project, [shot]),
		)
		self.assertEqual(
			{}, locations.missing_views(project, [frappe._dict(setting_prompt=self.ROOM, views_json="")])
		)


class TestSamePlaceDifferentWords(FrappeTestCase):
	def test_a_reworded_setting_of_a_place_already_drawn_uses_that_place(self):
		room = "Warm, cozy family dining room with traditional wooden table."
		project = frappe._dict(
			selected_media=[
				frappe._dict(reference_key=locations.location_key(room), label=f"Location 1: {room}"),
			]
		)
		self.assertEqual(
			locations.location_key(room),
			locations.place_key(project, "Family dining room with warm, inviting ambient lighting."),
		)
		self.assertEqual(
			locations.location_key("A sunny beach."), locations.place_key(project, "A sunny beach.")
		)
		self.assertEqual(
			locations.location_key(room) + locations.CLOSE,
			locations.view_key(
				project, "Family dining table", "Family dining room with warm, inviting ambient lighting."
			),
		)

	def test_a_place_picture_removed_from_the_references_is_replaced_on_its_scenes(self):
		room = "A dining room."
		project = frappe._dict(
			name="PRJ-X",
			selected_media=[
				frappe._dict(reference_key=locations.location_key(room), asset_version="ASTV-ROOM")
			],
		)
		shot = _shot("S1", room, environment="ASTV-REMOVED")
		with (
			patch("joymedia.services.review.comments._reseal_approved_plan"),
			patch("frappe.db.delete") as delete,
		):
			self.assertEqual(1, locations.assign_places(project, [shot]))
		self.assertEqual(["ASTV-ROOM"], [row.asset_version for row in shot.generation_inputs])
		delete.assert_called_once_with("Shot Reference", {"name": "S1-env"})
