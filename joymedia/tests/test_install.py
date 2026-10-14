from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia import install


class TestInstall(FrappeTestCase):
	def test_setup_is_idempotent_and_promotes_only_when_asked(self):
		with patch("joymedia.install.frappe.db.commit"):
			first = install.setup()
			second = install.setup()
		self.assertEqual(first["keyframe_workflow"], second["keyframe_workflow"])
		self.assertEqual(first["video_workflow"], second["video_workflow"])
		self.assertEqual(first["pipeline"], second["pipeline"])
		self.assertIsNotNone(first["pipeline"])

	def test_promotion_writes_the_site_config_only_with_the_flag(self):
		with patch("joymedia.install.frappe.db.commit"), patch("frappe.installer.update_site_config") as update, patch.object(
			frappe, "conf", frappe._dict(joymedia_active_generation_pipeline="PIPE-OLD", comfyui_base_url="http://x")
		):
			install.setup()
			update.assert_not_called()
			report = install.setup(promote=1)
		update.assert_called_once_with("joymedia_active_generation_pipeline", report["pipeline"])
