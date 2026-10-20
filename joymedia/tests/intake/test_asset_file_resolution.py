from unittest.mock import patch
import frappe
from frappe.tests.utils import FrappeTestCase
from joymedia.tests.support.e2e_setup import _generate_image_bytes
from joymedia.services.intake.assets import create_media_asset

class TestAssetFileResolution(FrappeTestCase):
 def setUp(self):
  super().setUp();frappe.set_user('Administrator')
  self.commit=patch.object(frappe.db,'commit');self.commit.start();self.addCleanup(self.commit.stop)
 def tearDown(self):
  frappe.db.rollback();super().tearDown()
 def test_file_name_only_upload_uses_resolved_url(self):
  file=frappe.get_doc({'doctype':'File','file_name':'name_only_asset.png','content':_generate_image_bytes(),'is_private':1}).insert(ignore_permissions=True)
  with patch('joymedia.services.intake.assets._get_duplicate_version',return_value=None):
   result=create_media_asset('Filename upload regression','Reference',file_name=file.name)
  self.assertEqual(file.file_url,frappe.db.get_value('Asset Version',result['asset_version'],'file'))
 def test_competing_url_cannot_override_the_resolved_file(self):
  file=frappe.get_doc({'doctype':'File','file_name':'authoritative_asset.png','content':_generate_image_bytes(),'is_private':1}).insert(ignore_permissions=True)
  with patch('joymedia.services.intake.assets._get_duplicate_version',return_value=None):
   result=create_media_asset('Authoritative upload regression','Reference',file_name=file.name,file_url='/private/files/unrelated.png')
  self.assertEqual(file.file_url,frappe.db.get_value('Asset Version',result['asset_version'],'file'))
