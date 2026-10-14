from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning.revisions import apply_project_shot_ai_revision


class TestAiDirector(FrappeTestCase):
	@patch("joymedia.api.storyboard.update_project_shot")
	@patch("joymedia.services.planning.revisions.frappe.get_doc")
	def test_apply_revision_preserves_image_and_motion_prompts(self, get_doc, update):
		project = frappe._dict(_require_write_access=lambda: None)
		get_doc.return_value = project
		update.return_value = {}

		apply_project_shot_ai_revision(
			"PROJECT-TEST", "SHOT-TEST",
			{
				"image_prompt": "A presenter and plate at an elegant dining table.",
				"generation_prompt": "The presenter raises the plate toward camera with a slow dolly-in.",
			},
		)

		self.assertEqual(
			{
				"image_prompt": "A presenter and plate at an elegant dining table.",
				"generation_prompt": "The presenter raises the plate toward camera with a slow dolly-in.",
			},
			update.call_args.args[2],
		)
