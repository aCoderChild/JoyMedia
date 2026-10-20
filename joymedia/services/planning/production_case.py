"""Apply a portable semantic case through the existing storyboard APIs.

No workflow, sampler, node IDs, native frame grid or model name belongs here.
The selected project pipeline owns execution and duration quantization.
"""
import copy
import json
import math

import frappe


def read_case(value):
    from joymedia.services.planning.plan_parsing import _normalized_motion_plan
    case = json.loads(value) if isinstance(value, str) else copy.deepcopy(value)
    if not isinstance(case, dict) or case.get('version') != 3:
        raise ValueError('Production case requires version 3.')
    if {'native', 'graph', 'model', 'sampler', 'workflow'} & set(case):
        raise ValueError('Model execution belongs in a separate deployment profile.')
    from joymedia.services.planning.shot_structure import reference_requirements
    requirements = case.get('reference_requirements')
    if not isinstance(requirements, dict):
        raise ValueError('Case requires named reference requirements.')
    reference_requirements([{'key': k, 'role': r.get('role')} for k, r in requirements.items() if isinstance(r, dict)])
    if any(not isinstance(r, dict) for r in requirements.values()):
        raise ValueError('Invalid case reference requirement.')
    shots = case.get('shots')
    if not isinstance(shots, list) or not 1 <= len(shots) <= 24:
        raise ValueError('A production case needs 1–24 shots.')
    for i, shot in enumerate(shots, 1):
        if not isinstance(shot, dict) or shot.get('shot_number') != i:
            raise ValueError('Case shots must be sequentially numbered.')
        if {'frames', 'fps', 'workflow', 'model', 'sampler', 'native'} & set(shot):
            raise ValueError('Case shots use seconds and semantic controls, not model settings.')
        duration = shot.get('duration_seconds')
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 30:
            raise ValueError('Case duration must be finite and between 0 and 30 seconds.')
        for field in ['name', 'action', 'opening', 'ending', 'image_prompt', 'sound']:
            if not isinstance(shot.get(field), str) or not shot[field].strip():
                raise ValueError('Case shot requires ' + field + '.')
        if shot.get('continuity') not in {'New Scene', 'Continue'} or i == 1 and shot['continuity'] == 'Continue':
            raise ValueError('Invalid case continuity.')
        keys = shot.get('references')
        if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not k for k in keys):
            raise ValueError('Case shot requires semantic reference keys.')
        if set(keys) - set(requirements):
            raise ValueError('Shot names an undeclared case reference.')
        plan = shot.get('motion_plan')
        if not isinstance(plan, dict) or not plan.get('shot_structure') or not plan.get('scene_contract'):
            raise ValueError('Case shots require a shot structure and physical scene contract.')
        shot['motion_plan'] = _normalized_motion_plan(plan, duration, shot['action'])
        actions = shot['motion_plan']['actions']
        if any(not math.isfinite(a['start']) or not math.isfinite(a['end'])
               or a['start'] < 0 or a['end'] <= a['start'] or a['end'] > duration for a in actions):
            raise ValueError('Case actions must lie inside the shot.')
        if any(a['end'] > b['start'] for a, b in zip(actions, actions[1:])):
            raise ValueError('Case actions must follow chronological, non-overlapping intervals.')
    if sum(s['duration_seconds'] for s in shots) > 120:
        raise ValueError('Production case exceeds 120 seconds.')
    return case


@frappe.whitelist(methods=['POST'])
def apply_production_case(project_name, case_json, reference_bindings, allow_incomplete=False):
    """Revise imported scenes; never approve frames, select takes or queue GPU work."""
    from joymedia.api.storyboard import update_project_shot, _assign_shot_references
    from joymedia.services.project.versions import assert_idle
    from joymedia.services.planning.plan_parsing import _rescale_motion_plan
    project = frappe.get_doc('Media Project', project_name)
    project._require_write_access()
    assert_idle([project.name])
    case = read_case(case_json)
    bindings = json.loads(reference_bindings) if isinstance(reference_bindings, str) else reference_bindings
    if not isinstance(bindings, dict):
        raise ValueError('Reference bindings must map case keys to project reference keys.')
    selected = {r.reference_key: r for r in project.selected_media or []}
    requirements = case.get('reference_requirements') or {}
    missing = set()
    for shot in case['shots']:
        for key in shot['references']:
            row = selected.get(bindings.get(key))
            if not row or row.reference_role != requirements.get(key, {}).get('role'):
                missing.add(key)
    if missing and str(allow_incomplete).lower() not in {'1', 'true'}:
        raise ValueError('Missing or incorrectly assigned project references: ' + ', '.join(sorted(missing)))
    shots = frappe.get_all('Shot', filters={'media_project': project.name, 'is_removed': 0},
                           fields=['name', 'duration_seconds'], order_by='shot_number')
    if len(shots) != len(case['shots']):
        raise ValueError('Import the case workbook before applying its structural plan.')
    # Validate and rescale all plans before the first write. The native pipeline's
    # quantized duration wins, with both actions and event dependencies rescaled.
    changes = []
    assignments = {}
    for shot, authored in zip(shots, case['shots']):
        plan = {'duration_seconds': float(shot.duration_seconds), 'motion_plan': copy.deepcopy(authored['motion_plan'])}
        _rescale_motion_plan(plan, authored['duration_seconds'])
        plan['motion_plan']['required_references'] = [
            {'key': bindings.get(k) or k, 'role': requirements[k]['role']} for k in authored['references']]
        changes.append((shot.name, {
            'generation_prompt': authored['action'] + '\n\nAudio: sound effects: ' + authored['sound'],
            'storyboard_action': authored['action'], 'image_prompt': authored['image_prompt'],
            'motion_plan_json': plan['motion_plan'], 'continuity_mode': authored['continuity'],
        }, authored))
        assignments[shot.name] = [bindings[k] for k in authored['references'] if k not in missing]
    _assign_shot_references(project, assignments)
    for name, values, authored in changes:
        update_project_shot(project.name, name, values)
        frappe.db.set_value('Shot', name, {'start_state': authored['opening'], 'end_state': authored['ending'],
                                         'handoff_type': 'ending' if authored is case['shots'][-1] else ''})
    return {'project': project.name, 'shots': len(changes), 'status': 'Needs Review',
            'unbound_references': sorted(missing), 'generation_started': False}
