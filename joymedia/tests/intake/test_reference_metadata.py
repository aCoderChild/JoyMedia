import json
from unittest import TestCase
from unittest.mock import patch

from joymedia.services.intake import vision


class TestReferenceMetadata(TestCase):
	def test_caption_refresh_preserves_view_provenance_and_negative_qualification(self):
		stored = {
			"source_asset_version": "original",
			"product_view": "back",
			"product_view_status": "ai_extrapolated_candidate",
			"product_identity_qualification_version": 2,
			"view_geometry_verified": False,
			"view_physical_plausibility_verified": False,
			"unknown_panels": "inferred and unverified",
			"subject_cutout": {"source_hash": "hash"},
			"identity_appearance": {"appearance": "Cream mascot with two round ears."},
			"identity_source_asset_version": "original",
			"identity_source_sha256": "original-hash",
			"qualified_pose_and_support": "seated",
			"qualified_pose_view": "front",
			"pose_qualification_version": 2,
			"environment_contract": {"physical_cast": []},
			"preparation_bridge": {"file": "/private/bridge.mp4", "timestamp": 2.5, "frame_sha256": "frame"},
		}
		with (
			patch.object(
				vision.frappe.db,
				"get_value",
				side_effect=lambda dt, name, field: json.dumps(stored)
				if field == "analysis_json"
				else "/reference.png",
			),
			patch.object(vision.frappe.db, "set_value") as save,
			patch.object(vision, "_image_data_url", return_value="image"),
			patch.object(
				vision,
				"describe_image",
				return_value={"description": "Fresh visible caption", "kind": "product"},
			),
		):
			result = vision.analyse_asset_version("view", as_product=True)
		self.assertEqual("Fresh visible caption", result["description"])
		for key, value in stored.items():
			self.assertEqual(value, result[key], key)
		self.assertEqual(
			"ai_extrapolated_candidate",
			json.loads(save.call_args.args[2]["analysis_json"])["product_view_status"],
		)
