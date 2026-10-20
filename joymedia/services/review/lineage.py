"""Database adapter for the selected footage's immutable generation inputs."""
import json

import frappe

from joymedia.services.scene.direction import direction_changed


def _copied_reference(version, originals):
    """Resolve only byte-identical, explicitly derived control copies.

    A new image, an unrelated identical upload, or broken lineage remains a
    different input. Edit-owned copies share their original file and hash.
    """
    if not version or version in originals:
        return version
    fields = ['source', 'derived_from', 'file', 'content_hash']
    current = frappe.db.get_value('Asset Version', version, fields, as_dict=True)
    if not current or not current.content_hash or not current.file:
        return version
    seen = {version}
    for _ in range(16):
        parent = current.derived_from
        if current.source != 'Derived' or not parent or parent in seen:
            break
        seen.add(parent)
        previous = frappe.db.get_value('Asset Version', parent, fields, as_dict=True)
        if not previous or (current.file, current.content_hash) != (previous.file, previous.content_hash):
            break
        if parent in originals:
            return parent
        current = previous
    return version


def take_direction_changed(shot):
    version = shot.selected_output_asset_version
    seen = set()
    for _ in range(8):
        if not version or version in seen:
            return False
        seen.add(version)
        source = frappe.db.get_value(
            'Asset Version', version, ['source_generation_attempt', 'derived_from'], as_dict=True
        )
        if not source:
            return False
        if not source.source_generation_attempt:
            version = source.derived_from
            continue
        task_name = frappe.db.get_value('Generation Attempt', source.source_generation_attempt, 'generation_task')
        task = frappe.db.get_value('Generation Task', task_name, ['generation_run', 'shot'], as_dict=True) if task_name else None
        if not task:
            return False
        try:
            snapshot = json.loads(frappe.db.get_value('Generation Run', task.generation_run, 'project_snapshot_json') or '{}')
        except (TypeError, ValueError):
            return False
        rows = snapshot.get('shots', []) if isinstance(snapshot, dict) else []
        if not isinstance(rows, list):
            return False
        frozen = next((row for row in rows if isinstance(row, dict) and row.get('shot') == task.shot), None)
        if not frozen:
            return False
        convert = getattr(shot, 'as_dict', None)
        current = convert() if callable(convert) else dict(shot)
        if 'authored_action' not in frozen and current.get('storyboard_action'):
            # Legacy takes did not bind the independently authored intention.
            # An explicit revision cannot inherit their old approval.
            return True
        if 'authored_action' in frozen and not current.get('authored_action'):
            from joymedia.services.scene.direction import authored_action
            from joymedia.services.project.context import _sheet_scenes
            authored = current if current.get('media_project') else frappe.get_doc('Shot', shot.name)
            project = frappe.get_doc('Media Project', authored.get('media_project'))
            imported = _sheet_scenes(project).get((authored.get('storyboard_beat') or '', authored.get('source_timing') or ''))
            current['authored_action'] = authored_action(authored, imported)
        if 'references' in frozen:
            references = shot.get('generation_inputs') or frappe.get_all(
                'Shot Reference', filters={'parent': shot.name, 'parenttype': 'Shot'}, fields=['asset_version']
            )
            current['references'] = [{'asset_version': row.get('asset_version')} for row in references]
            originals = {row.get('asset_version') for row in frozen['references'] if row.get('asset_version')}
            current['references'] = [{'asset_version': _copied_reference(row['asset_version'], originals)} for row in current['references']]
        return direction_changed(current, frozen)
    return False
