import json
from pathlib import Path
from unittest import TestCase
from types import SimpleNamespace
from joymedia.patches.register_tshirt_pipeline import execution_spec, GRAPH
from joymedia.workflow_adapters.comfyui_generic import GenericComfyUIAdapter

class TestEndpointGeometry(TestCase):
 def test_both_boundary_images_use_same_geometry(self):
  graph=json.loads(GRAPH.read_text());spec=execution_spec()
  first=graph['first_frame_size']['inputs'];last=graph['last_frame_size']['inputs']
  self.assertEqual({k:v for k,v in first.items() if k!='image'},{k:v for k,v in last.items() if k!='image'})
  self.assertEqual(graph['104']['inputs']['first_frame'],['first_frame_size',0])
  for key in ['first_frame_size','last_frame_size']:
   self.assertEqual({p['semantic'] for p in spec['parameters'] if p['node_key']==key},{'width','height'})
 def test_absent_endpoint_disconnects_the_whole_last_lane(self):
  adapter=GenericComfyUIAdapter();adapter.execution_spec=execution_spec()
  graph=adapter.finalize_workflow(json.loads(GRAPH.read_text()),SimpleNamespace(bindings=[]),{'first_frame':['start.png']})
  self.assertIsNone(graph['104']['inputs']['last_frame'])
 def test_explicit_endpoint_uses_normalized_lane(self):
  adapter=GenericComfyUIAdapter();adapter.execution_spec=execution_spec()
  graph=adapter.finalize_workflow(json.loads(GRAPH.read_text()),SimpleNamespace(bindings=[]),{'first_frame':['start.png'],'last_frame':['end.png']})
  self.assertEqual(graph['104']['inputs']['last_frame'],['last_frame_size',0])

class TestReferenceRoleSeparation(TestCase):
 def test_picture_numbers_follow_present_declared_role_slots(self):
  import frappe
  from joymedia.services.planning.prompts import _ordered_image_reference_roles
  shot=frappe._dict(references=[{'reference_role':'Environment'},{'reference_role':'Product'},{'reference_role':'Person'}])
  workflow={'execution_spec':{'capabilities':['multi_reference'],'input_preprocessing':{'optional_input_chains':[{'links':[{'role':'person'},{'role':'product'},{'role':'environment'}]}]}},'bindings':[{'required_input_role':'product'},{'required_input_role':'environment'}]}
  text=_ordered_image_reference_roles(shot,workflow)
  self.assertIn('Image 1 controls the actual advertised product',text)
  self.assertIn('Image 2 controls only the support surface',text)
  self.assertNotIn('Image 3',text)
 def test_legacy_workflow_does_not_guess_picture_numbers(self):
  import frappe
  from joymedia.services.planning.prompts import _ordered_image_reference_roles
  self.assertEqual('',_ordered_image_reference_roles(frappe._dict(references=[]),{'execution_spec':{}}))
