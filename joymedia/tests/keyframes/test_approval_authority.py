from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.keyframes import stage


class TestApprovalAuthority(FrappeTestCase):
	def test_approval_keeps_machine_notes_but_clears_a_pending_automatic_redraw(self):
		project = MagicMock()
		project.name = "PROJECT-X"
		shot = frappe._dict(
			name="SHOT-X",
			media_project=project.name,
			keyframe_artifact="ART-X",
			keyframe_signature="same",
			consistency_status="Redrawing",
			consistency_notes="possible issue",
		)
		with (
			patch.object(frappe, "get_doc", side_effect=[project, shot]),
			patch.object(stage, "keyframe_signature", return_value="same"),
			patch.object(frappe.db, "set_value") as write,
			patch.object(frappe.db, "commit"),
			patch.object(stage, "publish_project_event"),
		):
			stage.set_keyframe_approval(project.name, shot.name)
			project._require_write_access.assert_called_once()
			self.assertTrue(
				any(call.args[2:] == ("consistency_status", "Needs Review") for call in write.call_args_list)
			)
			self.assertFalse(any("consistency_notes" in str(call) for call in write.call_args_list))
