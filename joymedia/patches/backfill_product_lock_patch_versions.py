"""Give stored keyframe product locks immutable patch versions.

Locks saved before patches became Asset Versions only reference private files,
so the video stage's tracked fallback rejected them and failed whole runs.
The bytes are unchanged; only their immutable, project-owned record is added.
"""

import json

import frappe


def execute():
	from joymedia.services.keyframes.overlay import lock_patch_version

	for name in frappe.get_all(
		"Generation Artifact", filters={"product_lock_json": ["is", "set"]}, pluck="name"
	):
		artifact = frappe.get_doc("Generation Artifact", name)
		lock = json.loads(artifact.product_lock_json)
		changed = False
		for number, item in enumerate(lock.get("items") or [], 1):
			if item.get("patch_asset_version") or not item.get("file"):
				continue
			content = frappe.get_doc("File", {"file_url": item["file"]}).get_content()
			version = lock_patch_version(artifact, number, content, item.get("source_asset_version"))
			item.update(file=version.file, patch_asset_version=version.name)
			changed = True
		if changed:
			frappe.db.set_value(
				"Generation Artifact", name, "product_lock_json", json.dumps(lock), update_modified=False
			)
