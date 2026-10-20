"""Opt-in Ref2VA + original product conditioning, using native ComfyUI nodes.

Adapted from Comfy-Org/workflow_templates video_minimax_h3_r2v at
59a3b48bf369c5a15f29a1308bae3e279fa15505. Reuses the existing H3 sampler,
AV decode and JoyMedia generic adapter; no model code runs in Frappe.
Registration never promotes the pipeline or rewrites an existing workflow.
"""
import json
import frappe
from joymedia.patches.register_flux_pulid_h3_pipeline import GRAPHS, _pipeline_with

WORKFLOW_KEY = 'minimax_h3_ref2va_product'
GRAPH = GRAPHS / 'minimax_h3_ref2va.json'
MODEL = {
    'repository': 'Comfy-Org/MiniMax-H3',
    'revision': 'e5eb578a89295337b8ff433a035929ce0279e0b6',
    'file': 'diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors',
    'sha256': '9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779',
    'bytes': 20970379616,
}


def execution_spec():
    sizes = [{'width': 1344, 'height': 768}, {'width': 768, 'height': 1344}, {'width': 1024, 'height': 1024}]
    return {
        'capabilities': ['first_frame', 'last_frame', 'reference_image', 'native_audio'],
        'limits': {'max_frames': 124},
        'parameters': [
            {'semantic': 'seed', 'node_key': '15', 'input_name': 'noise_seed'},
            *[{'semantic': dimension, 'node_key': '104', 'input_name': dimension,
               'transform': 'nearest_size_dimension', 'dimension': dimension, 'options': sizes}
              for dimension in ('width', 'height')],
            {'semantic': 'frame_count', 'node_key': '111', 'input_name': 'value', 'transform': 'frames_to_seconds', 'fps': 24},
            {'semantic': 'output_prefix', 'node_key': '92', 'input_name': 'filename_prefix'},
        ],
        'outputs': {'primary': {'node_key': '92', 'media_type': 'Video'}},
        'metadata': {'frame_count': 124, 'output_fps': 24, 'produces_video': 1, 'produces_audio': 1},
        'conditional_inputs': [{
            'role': 'product', 'target': {'node_key': '104', 'input_name': 'ref_images.ref_image_1'},
            'when_present': ['product', 0], 'when_absent': None,
        }],
        'input_preprocessing': {'optional_input_chains': [{
            'target': {'node_key': '16', 'input_name': 'conditioning'}, 'base': ['guide_first', 0],
            'links': [{'role': 'last_frame', 'nodes': ['115', 'guide_last'],
                       'node': 'guide_last', 'input': 'positive'}],
        }]},
        'prompt_transforms': [
            {'node_key': '104', 'input_name': 'prompt', 'append_text':
             'Use <Picture 1> as the opening composition, subject identity, room, pose and action state. '
             'Continue only this authored shot; do not copy a reference photograph as a cutaway.'},
            {'node_key': '104', 'input_name': 'prompt', 'when_role_present': 'product', 'append_text':
             'Use <Picture 2> only for the exact advertised product silhouette, proportions, colours and printed artwork. '
             'It is the same physical product visible in <Picture 1>, not a second product or a new scene. '
             'Keep its artwork attached to its surface through perspective, motion and occlusion.'},
        ],
    }


def register_video():
    graph, spec = json.loads(GRAPH.read_text()), execution_spec()
    bindings = [
        {'binding_key': 'generation_prompt', 'node_key': '104', 'input_name': 'prompt', 'value_type': 'Text', 'required': 1},
        *[{'binding_key': role, 'node_key': node, 'input_name': 'image', 'required_input_role': role,
           'value_type': 'File Path', 'required': required, 'accepted_media_type': 'Image', 'allow_multiple': 0}
          for role, node, required in [('first_frame', '114', 1), ('last_frame', '115', 0), ('product', 'product', 0)]],
    ]
    for name in frappe.get_all('Generation Workflow', filters={'workflow_key': WORKFLOW_KEY}, pluck='name', order_by='version_number desc'):
        doc = frappe.get_doc('Generation Workflow', name)
        actual = [{key: row.get(key) for key in expected} for row, expected in zip(doc.bindings, bindings)]
        if (len(doc.bindings) == len(bindings) and actual == bindings
            and json.loads(doc.workflow_json) == graph and json.loads(doc.execution_spec) == spec):
            return name
    return frappe.get_doc({'doctype': 'Generation Workflow', 'workflow_key': WORKFLOW_KEY,
                           'adapter_key': 'comfyui_generic', 'workflow_json': json.dumps(graph),
                           'execution_spec': json.dumps(spec), 'bindings': bindings}).insert(ignore_permissions=True).name


def execute(keyframe_workflow=None):
    if not keyframe_workflow:
        from joymedia.services.workflows.pipeline import get_active_generation_pipeline, get_pipeline_steps
        steps = get_pipeline_steps(get_active_generation_pipeline().name)
        keyframe_workflow = steps[0].workflow
    if frappe.db.get_value('Generation Workflow', keyframe_workflow, 'output_media_type') != 'Image':
        raise ValueError('Ref2VA needs an image-producing keyframe stage.')
    video = register_video()
    pipeline = _pipeline_with(keyframe_workflow, video)
    if not pipeline:
        pipeline = frappe.get_doc({'doctype': 'Generation Pipeline', 'pipeline_key': 'reference_conditioned_product_video',
            'output_media_type': 'Video', 'steps': [
                {'step_key': 'keyframe', 'workflow': keyframe_workflow, 'prompt_source': 'Image', 'produces_artifact_role': 'Primary Image'},
                {'step_key': 'video', 'workflow': video, 'prompt_source': 'Motion', 'depends_on_step': 'keyframe',
                 'consumes_artifact_role': 'Primary Image', 'produces_artifact_role': 'Primary Video'},
            ]}).insert(ignore_permissions=True).name
    return {'workflow': video, 'pipeline': pipeline}
