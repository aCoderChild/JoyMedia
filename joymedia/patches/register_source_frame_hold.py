"""A declared source-frame presentation route; never promote it as a default."""
import json
from pathlib import Path
import frappe


def execute(image_workflow=None):
	graph=json.loads((Path(__file__).parents[1]/'workflow_adapters/graphs/source_frame_hold.json').read_text())
	spec={"capabilities":["reference_image","source_frame_hold"],"limits":{"max_frames":720},"parameters":[{"semantic":"frame_count","node_key":"frames","input_name":"amount"},{"semantic":"fps","node_key":"video","input_name":"frame_rate"},{"semantic":"output_prefix","node_key":"video","input_name":"filename_prefix"}],"outputs":{"primary":{"node_key":"video","media_type":"Video"}},"metadata":{"frame_count":720,"output_fps":24,"produces_video":1,"produces_audio":0}}
	name=None
	for n in frappe.get_all('Generation Workflow',filters={'workflow_key':'source_frame_hold'},pluck='name',order_by='version_number desc'):
		w=frappe.get_doc('Generation Workflow',n)
		if json.loads(w.workflow_json)==graph and json.loads(w.execution_spec)==spec:name=n;break
	if not name:
		w=frappe.get_doc(dict(doctype='Generation Workflow',workflow_key='source_frame_hold',adapter_key='comfyui_generic',workflow_json=json.dumps(graph),execution_spec=json.dumps(spec),bindings=[dict(binding_key='first_frame',node_key='source',input_name='image',required_input_role='first_frame',value_type='File Path',accepted_media_type='Image',required=1)])).insert(ignore_permissions=True);name=w.name
	if not image_workflow:
		from joymedia.services.workflows.pipeline import get_pipeline_steps
		active=frappe.conf.get("joymedia_active_generation_pipeline") or frappe.defaults.get_global_default("joymedia_active_generation_pipeline")
		if not active:
			return dict(workflow=name,pipeline=None)
		image_workflow=get_pipeline_steps(active)[0].workflow
		if frappe.db.get_value("Generation Workflow",image_workflow,"output_media_type")!="Image":
			return dict(workflow=name,pipeline=None)
	for n in frappe.get_all('Generation Pipeline',filters={'pipeline_key':'source_frame_presentation'},pluck='name',order_by='version_number desc'):
		p=frappe.get_doc('Generation Pipeline',n)
		if [s.workflow for s in p.steps]==[image_workflow,name]:return dict(workflow=name,pipeline=p.name)
	p=frappe.get_doc(dict(doctype='Generation Pipeline',pipeline_key='source_frame_presentation',steps=[dict(step_key='image',workflow=image_workflow,prompt_source='Image',produces_artifact_role='Primary Image'),dict(step_key='presentation',workflow=name,prompt_source='Motion',depends_on_step='image',consumes_artifact_role='Primary Image',produces_artifact_role='Primary Video')])).insert(ignore_permissions=True)
	return dict(workflow=name,pipeline=p.name)
