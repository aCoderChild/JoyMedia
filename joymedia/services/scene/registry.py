"""One identity per subject, with separately described reference poses and views."""

ROLES = {"character", "person", "people", "talent", "product"}


def reference_registry(records):
	groups, assigned = {}, {}
	for record in records:
		role = str(record.get("reference_role") or "").lower()
		if role not in ROLES:
			continue
		role = "person" if role in {"people", "talent"} else role
		identity = record.get("identity_key") or record.get("reference_key")
		version = record.get("asset_version")
		if not identity or not version:
			raise ValueError("Each cast or product reference needs an identity and an image version.")
		key = (role, identity)
		if (role, version) in assigned and assigned[(role, version)] != key:
			raise ValueError("A reference view cannot belong to two different identities.")
		assigned[(role, version)] = key
		group = groups.setdefault(
			key,
			{
				"identity": identity,
				"role": role,
				"label": record.get("label") or identity,
				"original": record.get("original") or {},
				"appearance": record.get("appearance") or "",
				"views": [],
			},
		)
		if not any(v["asset_version"] == version for v in group["views"]):
			group["views"].append(
				{
					k: record.get(k) or ""
					for k in (
						"reference_key",
						"asset_version",
						"content_hash",
						"file",
						"pose",
						"angle",
						"status",
					)
				}
			)
	return list(groups.values())


def scene_reference_bindings(references, registry):
	lookup = {(g["role"], v["asset_version"]): (g, v) for g in registry for v in g["views"]}
	bindings = []
	for reference in references or []:
		role = str(reference.get("reference_role") or reference.get("input_role") or "").lower()
		if role not in ROLES:
			continue
		role = "person" if role in {"people", "talent"} else role
		found = lookup.get((role, reference.get("asset_version")))
		if not found:
			raise ValueError(
				"Scene contains an unregistered cast or product view: " + str(reference.get("asset_version"))
			)
		group, view = found
		bindings.append(
			{"identity": group["identity"], "role": role, "original": group["original"], "view": dict(view)}
		)
	return bindings


def project_reference_registry(project):
	import frappe

	from joymedia.services.planning.pose_assets import _qualified_pose_metadata
	from joymedia.services.scene.prompt_scope import reference_description

	versions = {}

	def version(name):
		if name not in versions:
			asset = frappe.db.get_value(
				"Asset Version", name, ["name", "file", "content_hash", "analysis_json"], as_dict=True
			)
			if not asset:
				raise ValueError("Reference version is unavailable: " + str(name))
			asset["analysis"] = frappe.parse_json(asset.analysis_json or "{}") or {}
			versions[name] = asset
		return versions[name]

	records = []
	for row in project.get("selected_media") or []:
		role = str(row.get("reference_role") or "").lower()
		if role not in ROLES or not row.get("asset_version"):
			continue
		asset = version(row.asset_version)
		original, seen = asset, {asset.name}
		for _depth in range(4):
			parent = original["analysis"].get("source_asset_version")
			if not parent:
				break
			if parent in seen:
				raise ValueError("Reference view lineage contains a cycle.")
			seen.add(parent)
			original = version(parent)
		analysis = asset["analysis"]
		pose = _qualified_pose_metadata(analysis) if role != "product" else None
		records.append(
			{
				"identity_key": row.get("identity_key") or row.reference_key,
				"reference_key": row.reference_key,
				"reference_role": role,
				"label": row.get("label"),
				"asset_version": asset.name,
				"content_hash": asset.content_hash,
				"file": asset.file,
				"original": {
					"asset_version": original.name,
					"content_hash": original.content_hash,
					"file": original.file,
				},
				"appearance": reference_description(original["analysis"], role),
				"pose": (pose or {}).get("pose") or analysis.get("pose_and_support") or "",
				"angle": (pose or {}).get("view")
				or row.get("product_view")
				or analysis.get("product_view")
				or analysis.get("view")
				or "source",
				"status": "qualified_pose"
				if pose
				else analysis.get("product_view_status")
				or ("supplied" if original.name == asset.name else "unverified"),
			}
		)
	return reference_registry(records)
