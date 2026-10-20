import json
import unittest
from unittest.mock import patch
import frappe
from joymedia.services.editing.composer import product_lock_for


class TestAuthoredFrameLock(unittest.TestCase):
 def test_only_the_exact_immutable_source_patch_can_protect_the_take(self):
  lock={'canvas':[720,1280],'items':[{'patch_asset_version':'PATCH','file':'/private/files/patch.png','source_asset_version':'SOURCE'}]}
  snapshot=json.dumps({'media_project':'P','shots':[{'shot':'S','references':[{'reference_role':'first_frame','asset_version':'FRAME'}]}]})
  def doc(kind,name):
   return frappe._dict(preservation_evidence_json=json.dumps({'product_lock':lock})) if kind=='Asset Version' else frappe._dict(name='P')
  def value(kind,*args,**kwargs):return snapshot if kind=='Generation Run' else '/private/files/patch.png'
  with patch('joymedia.services.editing.composer.frappe.db.get_value',side_effect=value),patch('joymedia.services.editing.composer.frappe.get_doc',side_effect=doc),patch('joymedia.services.consistency.repair._project_asset_path') as checked:
   self.assertEqual(product_lock_for('R','S',[]),lock)
   self.assertEqual([call.args[1] for call in checked.call_args_list],['FRAME','PATCH'])
  with patch('joymedia.services.editing.composer.frappe.db.get_value',side_effect=lambda kind,*a,**k:snapshot if kind=='Generation Run' else '/private/files/different.png'),patch('joymedia.services.editing.composer.frappe.get_doc',side_effect=doc),patch('joymedia.services.consistency.repair._project_asset_path'):
   with self.assertRaisesRegex(ValueError,'does not match'):product_lock_for('R','S',[])

 def test_closing_hold_uses_the_frozen_authored_frame(self):
  from joymedia.services.editing.composer import _closing_hold_source
  snapshot=json.dumps({'media_project':'P','shots':[{'shot':'S','closing_hold_seconds':5,'references':[{'reference_role':'first_frame','asset_version':'FRAME'}]}]})
  with patch('joymedia.services.editing.composer.frappe.db.get_value',return_value=snapshot),patch('joymedia.services.editing.composer.frappe.get_doc',return_value=frappe._dict(name='P')),patch('joymedia.services.consistency.repair._project_asset_path',return_value='/frozen/frame.png') as checked:
   self.assertEqual(_closing_hold_source('R','S'),(5,'/frozen/frame.png'))
   self.assertEqual(checked.call_args.args[1],'FRAME')

 def test_static_actor_presentation_requires_an_authored_frame_and_no_action(self):
  from joymedia.services.consistency.retention import is_static_presentation
  plan={'camera_motion':'locked','scene_contract':{'version':1,'entities':[{'id':'subject','label':'the reference subject'}],'events':[],'properties':[{'entity':'subject','name':'motion','value':'stationary'}]}}
  scene={'duration_seconds':4,'references':[{'reference_role':'Character','asset_version':'ACTOR'}],'motion_plan_json':plan}
  self.assertFalse(is_static_presentation(scene))
  scene['references'].append({'reference_role':'first_frame','asset_version':'FRAME'})
  self.assertTrue(is_static_presentation(scene))
  plan['camera_motion']='pan'
  self.assertFalse(is_static_presentation(scene))
