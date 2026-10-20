import copy
import json
import random
import re
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import frappe
from joymedia.services.scene.contract import instruction, opening_claims, opening_instruction, read_contract
from joymedia.services.scene.evidence import SequenceCheck, claims_for, evaluate
from joymedia.services.scene.structure import structure_claims
from joymedia.services.keyframes.stage import keyframe_signature
from joymedia.services.planning.plan_parsing import _normalized_motion_plan, _rescale_motion_plan
from joymedia.services.planning.prompts import compile_prompt_for_documents, _scrub_options, _scrub_printable
from joymedia.services.planning.production import english_roles

CASES=json.loads((Path(__file__).parents[1]/'fixtures/scene_cases.json').read_text())


class TestProductIndependentContracts(TestCase):
 def test_each_product_uses_the_same_normalizer_image_prompt_motion_and_evidence_path(self):
  for case in CASES:
   with self.subTest(case=case['id']):
    plan=_normalized_motion_plan({'scene_contract':case['contract']},case['duration'],case['action'])
    shot=frappe._dict(name='S',shot_number=1,duration_seconds=case['duration'],image_prompt=case['opening'],generation_prompt=case['action'],motion_plan_json=plan,generation_inputs=[])
    project=frappe._dict(generation_mode='Continuous',global_instructions='')
    image=compile_prompt_for_documents(shot,project,prompt_source='image')
    motion=compile_prompt_for_documents(shot,project,prompt_source='motion')
    evidence=claims_for(plan,case['duration'],case['action'])
    for claim in structure_claims(plan['scene_contract']):
     self.assertIn(claim,image);self.assertIn(claim,motion)
     self.assertIn(claim,[row['claim'] for row in evidence])

 def test_no_mascot_packaging_or_four_leg_requirement_leaks_into_unrelated_products(self):
  for case in CASES[1:]:
   text=opening_instruction({'scene_contract':case['contract']}).lower()
   for unwanted in ('shera','mascot','cookie','tissue','corner legs','four leg','chair'):
    self.assertNotRegex(text, r"\b"+re.escape(unwanted)+r"\b")

 def test_a_pedestal_is_not_forced_to_have_four_legs(self):
  text=instruction({'scene_contract':next(case for case in CASES if case['id']=='single_pedestal')['contract']})
  self.assertIn('exactly 1 central pedestal',text);self.assertNotIn('legs',text)

 def test_hidden_parts_are_not_required_to_be_all_visible(self):
  contract=read_contract({'scene_contract':CASES[0]['contract']})
  self.assertIn('not every part must be visible',' '.join(structure_claims(contract)))
  self.assertNotIn('All declared parts must be visible',' '.join(structure_claims(contract)))

 def test_invalid_structural_counts_and_missing_entities_are_rejected(self):
  for count in (True,-1,1.5,'4',float('nan'),float('inf'),10**100):
   contract=copy.deepcopy(CASES[0]['contract']);contract['parts'][0]['count']=count
   with self.subTest(count=count),self.assertRaises(ValueError):read_contract({'scene_contract':contract})
  contract=copy.deepcopy(CASES[0]['contract']);contract['parts'][0]['entity']='missing'
  with self.assertRaises(ValueError):read_contract({'scene_contract':contract})


 def test_zero_parts_forbid_reference_absent_features_without_inventing_anatomy(self):
  for label in ('elongated leg shafts', 'handles', 'extra fins'):
   plan={'scene_contract':{'version':1,'entities':[{'id':'subject','label':'the reference subject'}],'parts':[{'entity':'subject','label':label,'count':0}]}}
   contract=read_contract(plan)
   claim=structure_claims(contract)[0]
   self.assertIn('has no '+label,claim)
   self.assertIn('including during motion',claim)
   self.assertEqual(0,contract['parts'][0]['count'])
  with self.assertRaises(ValueError):
   read_contract({'scene_contract':{'version':1,'entities':[{'id':'subject','label':'subject'}],'counts':[{'entity':'subject','count':0}]}})

 def test_typographical_or_duplicate_requirements_cannot_disappear_silently(self):
  for field in ('partz','property_rules'):
   with self.assertRaises(ValueError):read_contract({'scene_contract':{'version':1,field:[]}})
  contract=copy.deepcopy(CASES[0]['contract']);contract['parts'][0]['cout']=4
  with self.assertRaises(ValueError):read_contract({'scene_contract':contract})
  contract=copy.deepcopy(CASES[0]['contract']);duplicate=copy.deepcopy(contract['parts'][0]);duplicate['label']=duplicate['label'].upper();contract['parts'].append(duplicate)
  with self.assertRaises(ValueError):read_contract({'scene_contract':contract})

 def test_structural_edits_invalidate_approved_frames(self):
  shot=frappe._dict(image_prompt='Object on display',generation_inputs=[],motion_plan_json={'scene_contract':copy.deepcopy(CASES[0]['contract'])})
  before=keyframe_signature(shot);shot.motion_plan_json['scene_contract']['parts'][0]['count']=3
  self.assertNotEqual(before,keyframe_signature(shot))

 def test_timing_rescale_preserves_geometry_and_decorative_requirements(self):
  plan=_normalized_motion_plan({'scene_contract':CASES[1]['contract']},4,'Camera moves')
  scene={'duration_seconds':8,'motion_plan':plan};_rescale_motion_plan(scene,4)
  self.assertEqual(read_contract(scene['motion_plan'])['properties'],read_contract(plan)['properties'])

 def test_unknown_evidence_is_not_a_physical_or_brand_pass(self):
  plan={'scene_contract':CASES[3]['contract']};claims=claims_for(plan,4,'Camera moves')
  report=evaluate(SequenceCheck([], [{'index':0,'time':0}],claims,{}),{'observations':[]})
  self.assertNotEqual(report['status'],'Passed')

 def test_product_names_do_not_imply_packaging(self):
  for name in ('Bình gốm trang trí','Đĩa gốm','Nước hoa cao cấp'):
   result=english_roles(name+' stands on a plinth.',[{'role':'Product','label':name}],name)
   self.assertIn('advertised product',result.lower());self.assertNotIn('pack',result.lower())

 def test_a_box_prop_is_not_replaced_by_an_unrelated_product(self):
  shot=frappe._dict(references=[{'reference_role':'Product','asset_version':'V'}]);project=frappe._dict(references=[{'asset_version':'V','label':'Ceramic vase'}])
  with patch('joymedia.services.keyframes.overlay._cutout_path',return_value=None):options=_scrub_options(shot,project)
  self.assertEqual(_scrub_printable('A vase stands beside a box.',**options),'A vase stands beside a box.')

 def test_stress_normalization_across_authored_object_shapes(self):
  rng=random.Random(20261016)
  for _ in range(160):
   count=rng.randint(1,64);parts=rng.randint(1,64)
   value={'version':1,'entities':[{'id':'object','label':'the authored object'}],'counts':[{'entity':'object','count':count}],'parts':[{'entity':'object','label':'declared components','count':parts}],'properties':[{'entity':'object','name':'surface finish','value':rng.choice(['glazed','matte','polished','printed'])}]}
   contract=read_contract({'scene_contract':value})
   self.assertEqual(contract,read_contract({'scene_contract':json.loads(json.dumps(contract))}))
   self.assertIn(f'exactly {parts} declared components',' '.join(opening_claims({'scene_contract':contract})))

 def test_legacy_import_paths_are_compatible_without_duplicated_implementations(self):
  from joymedia.services.planning.scene_contract import read_contract as old
  from joymedia.services.review.temporal import claims_for as old_claims
  self.assertIs(old,read_contract);self.assertIs(old_claims,claims_for)

 def test_reference_changes_invalidate_footage_for_any_product(self):
  from joymedia.services.scene.direction import direction_changed
  for category in ('vase','plate','container','cosmetic'):
   frozen={'references':[{'asset_version':category+'-front','reference_role':'provider_slot_1'},{'asset_version':category+'-side'}]}
   current={'references':list(reversed(frozen['references']))}
   self.assertFalse(direction_changed(current,frozen))
   current['references']=[{'asset_version':category+'-revised-pattern'}]
   self.assertTrue(direction_changed(current,frozen))

 def test_a_new_conditioning_frame_does_not_reuse_an_old_take(self):
  from joymedia.services.scene.direction import direction_changed
  self.assertTrue(direction_changed({'keyframe_artifact':'new'},{'keyframe_artifact':'old'}))

 def test_a_plan_beyond_the_review_budget_is_rejected_before_generation(self):
  case=copy.deepcopy(CASES[0]['contract'])
  case['checks']=[{'id':f'check{i}','scope':'sequence','claim':'Preserve the authored scene'} for i in range(8)]
  case['properties']=[{'entity':'product','name':f'property{i}','value':'authored requirement'} for i in range(8)]
  case['events']=[{'id':f'event{i}','description':'Authored change','start':i*.25,'end':(i+1)*.25,'after':[f'event{i-1}'] if i else []} for i in range(8)]
  with self.assertRaisesRegex(ValueError,'budget'):_normalized_motion_plan({'scene_contract':case},4,'Action')


 def test_each_product_requests_review_when_a_structural_claim_is_violated(self):
  # Simulated judge responses verify handling, not image understanding accuracy.
  for case in CASES:
   with self.subTest(case=case['id']):
    claims=claims_for({'scene_contract':case['contract']},case['duration'],case['action'])
    structural=[row for row in claims if row['id'].startswith('structure.')]
    self.assertTrue(structural)
    for failed in structural:
     observations=[{'id':row['id'],'verdict':'violated' if row['id']==failed['id'] else 'supported','frames':[0],'reason':'Explicit simulated evidence'} for row in claims]
     check=SequenceCheck([], [{'index':0,'time':0}],claims,{'required_claim_ids':[row['id'] for row in claims]})
     result=evaluate(check,{'observations':observations})
     self.assertEqual(result['status'],'Needs Review')
     self.assertEqual(next(row for row in result['results'] if row['id']==failed['id'])['verdict'],'violated')

 def test_domain_modules_do_not_import_the_web_framework_or_provider_adapters(self):
  import ast
  root=Path(__file__).parents[2]/'services/scene'
  for path in root.glob('*.py'):
   tree=ast.parse(path.read_text())
   for node in ast.walk(tree):
    imports=[n.name for n in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
    self.assertFalse(any(name=='frappe' or '.workflow_adapters' in name or '.services.workflows' in name for name in imports),str(path))
