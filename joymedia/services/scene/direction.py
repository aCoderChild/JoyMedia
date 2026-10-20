"""Compare authored intentions and references, independently of providers and storage."""
import json


def _plan(value):
    if not value:
        return {}
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _assets(rows):
    return sorted(str(row.get('asset_version')) for row in rows or [] if isinstance(row, dict) and row.get('asset_version'))


def direction_changed(current, frozen):
    for field in ('authored_action', 'generation_prompt', 'image_prompt', 'motion_plan_json'):
        if field not in frozen:
            continue
        first, second = current.get(field) or '', frozen.get(field) or ''
        if field == 'motion_plan_json':
            first, second = _plan(first), _plan(second)
        if first != second:
            return True
    if 'references' in current and 'references' in frozen:
        if _assets(current['references']) != _assets(frozen['references']):
            return True
    if current.get('keyframe_artifact') and frozen.get('keyframe_artifact'):
        if current['keyframe_artifact'] != frozen['keyframe_artifact']:
            return True
    return False


def authored_action(shot, source_scene=None):
    """The client's intention must survive changes to a model's execution prompt."""
    return str(shot.get('storyboard_action') or (source_scene or {}).get('action')
               or shot.get('generation_prompt') or '').strip()
