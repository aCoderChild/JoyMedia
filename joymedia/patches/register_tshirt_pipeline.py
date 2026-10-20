"""Explicit opt-in T-shirt case pipeline; reuses the deployed multi-reference FLUX.2/H3 adapters.

Graph: existing Comfy-Org H3 FL2VA topology, turbo LoRA enabled at 8 steps,
plus a lossless decoded-frame PNG output for actual continuation handshakes.
"""
import json
from pathlib import Path
import frappe
from joymedia.patches.register_flux_pulid_h3_pipeline import _h3_spec, GRAPHS
from joymedia.patches.register_flux2_klein_pipeline import _register_keyframe

WORKFLOW_KEY='tshirt_h3_fl2va_turbo8'
GRAPH=GRAPHS/'t_shirt_h3_i2v.json'


def execution_spec():
 spec=_h3_spec()
 spec['capabilities']=['first_frame','last_frame','native_audio']
 spec['limits']={'max_frames':124}
 # Symmetric endpoint preprocessing follows the upstream optional I2V/FL2V topology.
 for node in ('first_frame_size','last_frame_size'):
  for dimension in ('width','height'):
   original=next(m for m in spec['parameters'] if m['semantic']==dimension)
   spec['parameters'].append({**original,'node_key':node,'input_name':dimension})
 spec['conditional_inputs'][0]['when_present']=['last_frame_size',0]
 spec['outputs']['last_frame']={'node_key':'save_last_image','media_type':'Image'}
 spec['parameters'] += [
  {'semantic':'last_frame_index','node_key':'last_image','input_name':'batch_index'},
  {'semantic':'last_frame_prefix','node_key':'save_last_image','input_name':'filename_prefix'}]
 spec['delivery']={'width':1440,'height':2560,'fps':24,'audio_sample_rate':44100,'audio_channels':2,'crf':14,'preset':'slow','sharpen':.9,'contrast':1.03,'brightness':.01,'saturation':1.04}
 return spec


def execute(keyframe_workflow=None):
 graph=json.loads(GRAPH.read_text());spec=execution_spec()
 bindings=[{'binding_key':'generation_prompt','node_key':'104','input_name':'prompt','value_type':'Text','required':1}]
 for role,node,required in [('first_frame','114',1),('last_frame','115',0)]:
  bindings.append({'binding_key':role,'node_key':node,'input_name':'image','required_input_role':role,'value_type':'File Path','required':required,'accepted_media_type':'Image','allow_multiple':0})
 workflow=None
 for name in frappe.get_all('Generation Workflow',filters={'workflow_key':WORKFLOW_KEY},pluck='name',order_by='version_number desc'):
  doc=frappe.get_doc('Generation Workflow',name)
  if json.loads(doc.workflow_json)==graph and json.loads(doc.execution_spec)==spec:
   workflow=name;break
 if not workflow:
  workflow=frappe.get_doc({'doctype':'Generation Workflow','workflow_key':WORKFLOW_KEY,'adapter_key':'comfyui_generic','workflow_json':json.dumps(graph),'execution_spec':json.dumps(spec),'bindings':bindings}).insert(ignore_permissions=True).name
 keyframe=keyframe_workflow or _register_keyframe();pipeline=None
 if frappe.db.get_value('Generation Workflow',keyframe,'output_media_type')!='Image':
  raise ValueError('The selected keyframe workflow must produce images.')
 for name in frappe.get_all('Generation Pipeline',filters={'pipeline_key':'tshirt_flux_h3_turbo8'},pluck='name'):
  p=frappe.get_doc('Generation Pipeline',name)
  if [s.workflow for s in p.steps]==[keyframe,workflow]:pipeline=name;break
 if not pipeline:
  pipeline=frappe.get_doc({'doctype':'Generation Pipeline','pipeline_key':'tshirt_flux_h3_turbo8','steps':[
   {'step_key':'keyframe','workflow':keyframe,'prompt_source':'Image','produces_artifact_role':'Primary Image'},
   {'step_key':'video','workflow':workflow,'prompt_source':'Motion','depends_on_step':'keyframe','consumes_artifact_role':'Primary Image','produces_artifact_role':'Primary Video'}]}).insert(ignore_permissions=True).name
 return {'workflow':workflow,'keyframe_workflow':keyframe,'pipeline':pipeline}


def pin_project(project_name,pipeline_name):
 frappe.only_for('System Manager')
 from joymedia.services.project.versions import assert_idle
 from joymedia.services.workflows.pipeline import get_pipeline_steps
 assert_idle([project_name]);get_pipeline_steps(pipeline_name)
 project=frappe.get_doc('Media Project',project_name);project._require_write_access()
 value=frappe.defaults.get_global_default('joymedia_project_generation_pipelines') or '{}'
 pins=json.loads(value) if isinstance(value,str) else value
 pins[project_name]=pipeline_name
 frappe.defaults.set_global_default('joymedia_project_generation_pipelines',json.dumps(pins))
 project.follow_active_pipeline()
 return {'project':project_name,'pipeline':pipeline_name}
