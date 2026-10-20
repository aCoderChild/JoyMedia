import unittest
from joymedia.services.scene.artwork import placements, fit_box


class TestArtworkPlacement(unittest.TestCase):
	def test_same_placement_scales_without_changing_source_proportions(self):
		box = [.1, .4, .4, .3]
		self.assertEqual((100, 550, 400, 150), fit_box((1000, 1000), (800, 300), box))
		self.assertEqual((200, 1100, 800, 300), fit_box((2000, 2000), (800, 300), box))

	def test_invalid_coordinates_or_ambiguous_duplicate_assets_are_rejected(self):
		for box in ([0, 0, -1, 1], [0, 0, 2, 1], [0, float('nan'), .5, .5], [True, 0, .5, .5]):
			with self.assertRaises(ValueError):
				placements({'artwork_placements': [{'asset_version':'SOURCE', 'box':box}]})
		with self.assertRaises(ValueError):
			placements({'artwork_placements': [{'asset_version':'SOURCE', 'box':[0,0,.5,.5]}]*2})

	def test_valid_controls_survive_plan_serialization(self):
		self.assertEqual([{'asset_version':'VASE', 'box':[.2,.3,.4,.4]}], placements('{"artwork_placements":[{"asset_version":"VASE","box":[0.2,0.3,0.4,0.4]}]}'))
		self.assertEqual([], placements(None))

	def test_placement_entity_must_exist_in_valid_contract(self):
		with self.assertRaises(ValueError):
			placements({"scene_contract":"invalid", "artwork_placements":[{"asset_version":"SOURCE","entity":"product","box":[0,0,.5,.5]}]})
		with self.assertRaises(ValueError):
			placements({"scene_contract":{"version":1,"entities":[]}, "artwork_placements":[{"asset_version":"SOURCE","entity":"unknown","box":[0,0,.5,.5]}]})


class TestSurfaceContact(unittest.TestCase):
	def test_contact_is_frame_bound_and_rejects_floating_or_overhanging_art(self):
		import hashlib
		from PIL import Image
		from joymedia.services.scene.artwork import validate_surface_contact

		background = b"the immutable room frame"
		asset = Image.new("RGBA", (40, 20), (50, 90, 140, 255))
		surface = {"background_sha256": hashlib.sha256(background).hexdigest(), "polygon": [[.1,.4],[.9,.4],[.9,.6],[.1,.6]]}
		proof = validate_surface_contact(background, (100,100), asset, (30,30,40,20), surface)
		self.assertEqual("surface_contact_2d", proof["kind"])
		self.assertEqual(5, len(proof["contact_points"]))
		for box in [(30,65,40,20), (30,5,40,20), (80,30,40,20)]:
			with self.assertRaisesRegex(ValueError, "outside its supporting surface"):
				validate_surface_contact(background, (100,100), asset, box, surface)
		for value in [None, {**surface,"background_sha256":"another frame"}, {**surface,"polygon":[[.1,.4],[float("nan"),.4],[.9,.6]]}]:
			with self.assertRaises(ValueError):validate_surface_contact(background,(100,100),asset,(30,30,40,20),value)

	def test_product_only_source_holds_do_not_automatically_certify_placement(self):
		from joymedia.services.consistency.retention import needs_candidate_review

		for source in ["tissue", "ceramic", "bottle"]:
			scene = {"reference_retention":{"version":1},"references":[{"reference_role":"Product","asset_version":source}],"duration_seconds":5,"render_strategy":"controlled_source_presentation"}
			self.assertTrue(needs_candidate_review(scene))
			self.assertFalse(needs_candidate_review({**scene,"closing_hold_seconds":5}))

	def test_an_unmeasured_room_fallback_cannot_create_a_protected_product(self):
		import frappe
		from unittest.mock import patch
		from joymedia.services.keyframes import overlay
		from joymedia.services.consistency.retention import RetentionRejected

		snapshot = {"shots":[{"shot":"SCENE", "shot_number":1, "references":[]},{"shot":"END", "shot_number":2}]}
		values = {("Generation Attempt","ATT"):frappe._dict(generation_task="TASK"), ("Generation Task","TASK"):("SCENE","RUN"), ("Generation Run","RUN"):frappe.as_json(snapshot)}
		with patch.object(frappe.db,"get_value",side_effect=lambda dt,name,*a,**kw:values[(dt,name)]), patch.object(overlay,"pasted_references",return_value=[{"role":"product","asset_version":"ANY-SOURCE","path":"unused.png"}]), patch.object(overlay,"composite_subjects") as composite:
			with self.assertRaisesRegex(RetentionRejected,"Heuristic product placement"):
				overlay.paste_subjects_into_keyframe(frappe._dict(name="ATT"),b"unchanged frame")
		composite.assert_not_called()
