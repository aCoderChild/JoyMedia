from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning.prompts import compile_prompt_for_documents


class TestReferenceOrder(FrappeTestCase):
	def test_environment_ordinal_includes_the_supplied_product_picture(self):
		shot = frappe._dict(name="SHOT-X", shot_number=1, image_prompt="The mascot holds a cookie.",
			generation_prompt="The mascot eats a cookie.", setting_prompt="A warm wooden room.", character_mode="Draw in scene",
			references=[{"reference_role": "Character", "asset_version": "AV-BEAR"},
				{"reference_role": "Product", "asset_version": "AV-PACK"}, {"reference_role": "Environment", "asset_version": "AV-ROOM"}])
		project = frappe._dict(references=[{"asset_version": "AV-BEAR", "label": "mascot"},
			{"asset_version": "AV-PACK", "label": "product pack"}, {"asset_version": "AV-ROOM", "label": "room"}])
		with patch("joymedia.services.keyframes.overlay.describe_colours", return_value="cream"), patch(
			"joymedia.services.keyframes.overlay._cutout_path", return_value=None
		):
			prompt = compile_prompt_for_documents(shot, project, prompt_source="image")
		self.assertIn("room of picture 3", prompt)
		self.assertNotIn("room of picture 2", prompt)
