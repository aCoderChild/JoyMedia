from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.review.physical_audit import reference_fit_findings


class TestReferenceFit(FrappeTestCase):
	def setUp(self):
		# Surface material has its own test below; these sequences cover other findings.
		patcher = patch(
			"joymedia.services.planning.pose_assets.character_look", return_value={"surface": None}
		)
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_generated_pose_still_checks_original_identity_and_eye_design(self):
		shot = frappe._dict(
			generation_inputs=[frappe._dict(reference_role="Character", asset_version="POSE")]
		)
		seen_pairs = []

		def asset_value(_dt, name, field):
			if field == "analysis_json":
				return '{"source_asset_version":"SOURCE"}' if name == "POSE" else "{}"
			return {"POSE": "/pose.png", "SOURCE": "/source.png"}.get(name)

		def observe(images, prompt, **_kwargs):
			if "Compare ONLY mascot/person anatomy" in prompt:
				return {"distortion": False}
			if isinstance(images, list):
				seen_pairs.append(images)
				return {
					"comparable": False,
					"identity_match": None,
					"proportions_match": None,
					"anatomy_connected": None,
				}
			if "eye drawing" in prompt:
				return {"eye_shape": "closed_smiling_arcs" if images == "/source.png" else "open_dots"}
			if "head" in prompt:
				return {"head_accessories": []}
			return {}

		with patch("frappe.db.get_value", side_effect=asset_value):
			findings = reference_fit_findings(shot, "/frame.png", ask=observe)
		self.assertIn(["/source.png", "/frame.png"], seen_pairs)
		self.assertIn("Critical identity: character eye design changed from the original reference", findings)
		self.assertTrue(any("stale or missing pose qualification" in item for item in findings))

	def test_limb_topology_is_checked_independently_of_identity(self):
		shot = frappe._dict(
			generation_inputs=[frappe._dict(reference_role="Character", asset_version="CHAR")]
		)

		def observe(_images, prompt, **_kwargs):
			if "Compare ONLY mascot/person anatomy" in prompt:
				return {"distortion": True, "evidence": "The forelimb is longer than in the selected pose."}
			return {
				"comparable": True,
				"identity_match": True,
				"proportions_match": True,
				"anatomy_connected": True,
			}

		with patch(
			"frappe.db.get_value",
			side_effect=lambda _dt, _name, field: "/character.png" if field == "file" else "{}",
		):
			findings = reference_fit_findings(shot, "/frame.png", ask=observe)
		self.assertTrue(
			any(item.startswith("Critical geometry: character limb topology") for item in findings)
		)

	def test_uncertain_limb_topology_cannot_pass_as_verified(self):
		shot = frappe._dict(
			generation_inputs=[frappe._dict(reference_role="Character", asset_version="CHAR")]
		)

		def observe(_images, prompt, **_kwargs):
			if "Compare ONLY mascot/person anatomy" in prompt:
				return {"distortion": None, "evidence": "The arm is hidden."}
			return {
				"comparable": True,
				"identity_match": True,
				"proportions_match": True,
				"anatomy_connected": True,
			}

		with patch(
			"frappe.db.get_value",
			side_effect=lambda _dt, _name, field: "/character.png" if field == "file" else "{}",
		):
			findings = reference_fit_findings(shot, "/frame.png", ask=observe)
		self.assertTrue(any("limb topology remains unverified" in item for item in findings))

	def test_topology_boolean_without_evidence_does_not_clear_the_review(self):
		shot = frappe._dict(
			generation_inputs=[frappe._dict(reference_role="Character", asset_version="CHAR")]
		)
		with patch(
			"frappe.db.get_value",
			side_effect=lambda _dt, _name, field: "/character.png" if field == "file" else "{}",
		):
			findings = reference_fit_findings(
				shot, "/frame.png", ask=lambda *args, **kwargs: {"distortion": False, "evidence": ""}
			)
		self.assertTrue(any("topology remains unverified" in item for item in findings))

	def test_distorted_character_part_ratio_is_critical(self):
		shot = frappe._dict(
			generation_inputs=[frappe._dict(reference_role="Character", asset_version="CHAR")]
		)
		with patch(
			"frappe.db.get_value",
			side_effect=lambda _dt, _name, field: "/character.png" if field == "file" else "{}",
		):
			findings = reference_fit_findings(
				shot,
				"/frame.png",
				ask=lambda *_args, **_kwargs: {
					"comparable": True,
					"identity_match": True,
					"proportions_match": False,
					"anatomy_connected": True,
				},
			)
		self.assertTrue(
			any(item.startswith("Critical identity") and "part ratios" in item for item in findings)
		)

	def test_cropped_reference_comparison_remains_unverified(self):
		shot = frappe._dict(generation_inputs=[frappe._dict(reference_role="Product", asset_version="PACK")])
		with patch("frappe.db.get_value", return_value="/product.png"):
			findings = reference_fit_findings(
				shot,
				"/frame.png",
				ask=lambda *_args, **_kwargs: {
					"comparable": False,
					"identity_match": None,
					"proportions_match": None,
				},
			)
		self.assertTrue(any("not visible well enough" in finding for finding in findings))
		self.assertTrue(
			any("product angle against its support remains unverified" in finding for finding in findings)
		)

	def test_a_plush_frame_of_a_smooth_mascot_is_a_critical_identity_change(self):
		shot = frappe._dict(
			generation_inputs=[frappe._dict(reference_role="Character", asset_version="POSE")]
		)

		def asset_value(_dt, name, field):
			if field == "analysis_json":
				return '{"source_asset_version":"SOURCE"}' if name == "POSE" else "{}"
			return {"POSE": "/pose.png", "SOURCE": "/source.png"}.get(name)

		def observe(images, prompt, **_kwargs):
			if "Compare ONLY mascot/person anatomy" in prompt:
				return {"distortion": False}
			if isinstance(images, list):
				return {
					"comparable": True,
					"identity_match": True,
					"proportions_match": True,
					"anatomy_connected": True,
				}
			if "eye drawing" in prompt:
				return {"eye_shape": "closed_smiling_arcs"}
			if "head" in prompt:
				return {"head_accessories": []}
			return {}

		surfaces = {"/source.png": "smooth_seamless", "/frame.png": "fur_or_plush"}
		with (
			patch("frappe.db.get_value", side_effect=asset_value),
			patch(
				"joymedia.services.planning.pose_assets.character_look",
				side_effect=lambda image: {"surface": surfaces.get(image)},
			),
		):
			findings = reference_fit_findings(shot, "/frame.png", ask=observe)
		self.assertIn(
			"Critical identity: character surface changed from smooth_seamless to fur_or_plush", findings
		)
