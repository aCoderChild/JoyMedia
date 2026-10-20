"""Small, deterministic strategy plan for arbitrary identities and providers."""

import hashlib
import json


def identity_plan(references, capabilities=()):
	"""Freeze the source set and distinguish guidance from exact-art preservation.

	Capabilities name controls a workflow implements. They never imply that a
	model has passed visual acceptance or can synthesize exact packaging text.
	"""
	groups = {}
	for reference in references or []:
		version = reference.get("asset_version")
		if not version:
			continue
		role = (
			str(reference.get("input_role") or reference.get("reference_role") or "general")
			.strip()
			.lower()
			.replace(" ", "_")
		)
		role = {"people": "person", "talent": "person"}.get(role, role)
		if role not in {"character", "person", "people", "talent", "product", "logo"}:
			continue
		key = reference.get("identity_key") or reference.get("reference_key") or version
		group = groups.setdefault((role, key), {"identity": key, "role": role, "sources": []})
		group["sources"].append({"asset_version": version, "content_hash": reference.get("content_hash")})
	result = []
	available = set(capabilities)
	for key in sorted(groups):
		group = groups[key]
		group["sources"] = sorted(group["sources"], key=lambda source: source["asset_version"])
		if group["role"] in {"product", "logo"}:
			group.update(
				strategy="source_artwork",
				requires=["authored_plane_or_matte", "placement_and_occlusion"],
				acceptance="source_coverage_and_visual_review",
			)
		else:
			group.update(
				strategy="rigged_render" if "rigged_render" in available else "reference_conditioned",
				requires=[]
				if "rigged_render" in available
				else [
					"approved_identity_views",
					"reference_image_or_video",
					"reference_topology_and_proportions",
				],
				acceptance="identity_review",
			)
		result.append(group)
	plan = {"version": 1, "identities": result, "capabilities": sorted(available)}
	plan["fingerprint"] = hashlib.sha256(
		json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
	).hexdigest()
	return plan
