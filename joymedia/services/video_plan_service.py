import json

import frappe
from frappe import _


@frappe.whitelist()
def apply_video_plan_from_ui(media_project_name: str = None, plan_json: str = None):
	frappe.has_permission(
		"Media Project",
		"write",
		media_project_name,
		throw=True,
	)

	plan = parse_video_plan(plan_json)

	created_shots = apply_video_plan(
		media_project_name=media_project_name,
		plan=plan,
	)

	return {
		"media_project": media_project_name,
		"shots": created_shots,
	}


def parse_video_plan(plan_json: str):
	try:
		return json.loads(plan_json)
	except (TypeError, ValueError, json.JSONDecodeError):
		frappe.throw(_("Invalid video plan JSON."))


def apply_video_plan(media_project_name: str = None, plan: dict = None):
	project = frappe.get_doc("Media Project", media_project_name)
	from joymedia.joymedia.doctype.media_project.media_project import _project_settings
	settings = _project_settings(project)
	_validate_plan_shape(plan)
	mode = {"Independent": "Multi-shot", "Chained": "Continuous", "Consistency": "Continuous"}.get(
		settings.generation_mode, settings.generation_mode or "Multi-shot"
	)
	if mode not in ("Multi-shot", "Continuous"):
		frappe.throw(_("Select Continuous or Multi-shot generation mode."))
	uses_keyframe_fields = any(
		fieldname in shot
		for shot in plan["shots"]
		for fieldname in ("first_frame_reference_image_index", "last_frame_reference_image_index")
	)
	project_references = {
		getattr(row, "reference_key", None): row
		for row in project.selected_media or []
		if getattr(row, "reference_key", None)
	}
	workflow_contract = None
	if settings.workflow:
		from joymedia.services.workflow_resolver import get_workflow_input_contract
		workflow_contract = get_workflow_input_contract(frappe.get_doc("Generation Workflow", settings.workflow))
	contract_by_role = {item["role"]: item for item in (workflow_contract or [])}
	_assign_reference_pool(plan, project, settings, contract_by_role, project_references, mode)
	for shot in plan["shots"]:
		role_counts = {}
		for reference in shot.get("references") or []:
			role = frappe.scrub(reference.get("usage_role") or "")
			contract = contract_by_role.get(role)
			if workflow_contract is not None and not contract:
				frappe.throw(_("Workflow does not support Shot Reference role '{0}'.").format(role))
			role_counts[role] = role_counts.get(role, 0) + 1
			if contract and role_counts[role] > 1 and not contract["allow_multiple"]:
				frappe.throw(_("Workflow input role '{0}' accepts exactly one reference.").format(role))
			if contract and contract.get("max_count") and role_counts[role] > contract["max_count"]:
				frappe.throw(
					_("Workflow input role '{0}' accepts at most {1} references.").format(
						role, contract["max_count"]
					)
				)
			if contract and contract["accepted_media_type"] != "Any":
				project_reference = project_references.get(reference.get("reference_key"))
				media_type = (
					frappe.db.get_value("Media Asset", frappe.db.get_value(
						"Asset Version", project_reference.asset_version, "media_asset"
					), "media_type")
					if project_reference else None
				)
				if media_type != contract["accepted_media_type"]:
					frappe.throw(
						_("Workflow input role '{0}' accepts {1} media, not {2}.").format(
							role, contract["accepted_media_type"], media_type or "unknown"
						)
					)
		for contract in workflow_contract or []:
			count = role_counts.get(contract["role"], 0)
			if count < contract.get("min_count", 0):
				frappe.throw(
					_(
						"Shot {0} needs {1} reference image(s) for the selected workflow. "
						"Choose H3 I2V Production for one image per shot, or add the required "
						"additional references."
					).format(
						shot.get("shot_number"), contract["min_count"]
					)
				)

	shot_numbers = [shot["shot_number"] for shot in plan["shots"]]
	if len(shot_numbers) != len(set(shot_numbers)):
		frappe.throw(_("Video plan contains duplicate shot numbers."))

	reference_image_indexes = set()
	for shot in plan["shots"]:
		for fieldname in (
			"reference_image_index",
			"first_frame_reference_image_index",
			"last_frame_reference_image_index",
		):
			if shot.get(fieldname) is not None:
				reference_image_indexes.add(shot[fieldname])
	asset_version_by_index = {}
	required_input_role = None
	if reference_image_indexes:
		from joymedia.services.project_image_manifest import get_project_image_manifest

		image_manifest = get_project_image_manifest(project.name)
		asset_version_by_index = {image["index"]: image["asset_version"] for image in image_manifest}
		if not settings.workflow:
			frappe.throw(_("The Media Project requires a Workflow."))

		workflow = frappe.get_doc("Generation Workflow", settings.workflow)
		required_input_roles = {
			frappe.scrub(binding.required_input_role)
			for binding in workflow.bindings
			if binding.binding_key in {"first_frame", "last_frame"}
			and binding.required
			and binding.required_input_role
		}
		if len(required_input_roles) > 1:
			frappe.throw(
				_("Video plan application requires exactly one required Generation Input role.")
			)
		required_input_role = next(iter(required_input_roles), None)

	existing_shots = frappe.get_all(
		"Shot",
		filters={"media_project": project.name, "is_removed": 0},
		pluck="name",
	)
	if existing_shots:
		if frappe.db.exists("Generation Run", {"media_project": project.name}):
			frappe.throw(
				_(
					"This storyboard cannot be replaced after generation starts. "
					"Create a new revision instead."
				)
			)

		for shot_name in existing_shots:
			frappe.delete_doc("Shot", shot_name, ignore_permissions=True)

	created_shots = []
	resolved_shot_inputs = []
	shot_docs = []

	for shot in plan["shots"]:
		doc = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": project.name,
				"shot_number": shot["shot_number"],
				"shot_name": shot.get("shot_name") or f"Shot {shot['shot_number']}",
				"generation_prompt": shot["generation_prompt"],
			}
		)
		doc.duration_seconds = shot["duration_seconds"]
		if shot.get("planned_frame_count"):
			doc.planned_frame_count = int(shot["planned_frame_count"])
		for reference in shot.get("references") or []:
			if not isinstance(reference, dict) or not reference.get("reference_key"):
				frappe.throw(_("Every Shot Reference must contain a reference_key."))
			key = reference["reference_key"]
			project_reference = project_references.get(key)
			if not project_reference:
				frappe.throw(_("Unknown Project Reference key '{0}'.").format(key))
			usage_role = frappe.scrub(reference.get("usage_role") or "general")
			if not project_reference.asset_version:
				frappe.throw(_("Project Reference '{0}' has no Asset Version.").format(key))
			doc.append(
				"generation_inputs",
				{"reference_role": usage_role, "asset_version": project_reference.asset_version},
			)
		first_reference_index = shot.get("first_frame_reference_image_index")
		if first_reference_index is None:
			first_reference_index = shot.get("reference_image_index")
		last_reference_index = shot.get("last_frame_reference_image_index")
		first_asset_version = asset_version_by_index.get(first_reference_index)
		last_asset_version = asset_version_by_index.get(last_reference_index)
		if first_reference_index is not None and not first_asset_version:
			frappe.throw(
				_("First-frame reference image index {0} could not be resolved.").format(
					first_reference_index
				)
			)
		if last_reference_index is not None and not last_asset_version:
			frappe.throw(
				_("Last-frame reference image index {0} could not be resolved.").format(
					last_reference_index
				)
			)

		if mode == "Multi-shot" and uses_keyframe_fields and reference_image_indexes and (
			first_asset_version is None or last_asset_version is None
		):
			frappe.throw(
				_("Multi-shot requires first-frame and last-frame references for every shot.")
			)

		if first_asset_version and (mode == "Multi-shot" or shot["shot_number"] == 1):
			if not required_input_role:
				frappe.throw(_("The Media Project workflow has no required Generation Input role."))
			doc.append(
				"generation_inputs",
				{
					"reference_role": required_input_role,
					"asset_version": first_asset_version,
				},
			)
		if mode == "Multi-shot" and last_asset_version:
			doc.append(
				"generation_inputs",
				{
					"reference_role": "last_frame",
					"asset_version": last_asset_version,
				},
			)
		resolved_shot_inputs.append(
			{
				"shot_number": shot["shot_number"],
				"first_frame": first_asset_version,
				"last_frame": last_asset_version,
			}
		)
		shot_docs.append(doc)

	if mode == "Multi-shot" and uses_keyframe_fields:
		resolved_shot_inputs.sort(key=lambda item: item["shot_number"])
		for current, following in zip(resolved_shot_inputs, resolved_shot_inputs[1:]):
			if current["last_frame"] != following["first_frame"]:
				frappe.throw(
					_("Multi-shot boundary is invalid between shots {0} and {1}.").format(
						current["shot_number"], following["shot_number"]
					)
				)

	for doc in shot_docs:
		doc.insert(ignore_permissions=True)
		created_shots.append(doc.name)

	return created_shots


def _assign_reference_pool(plan, project, settings, contract_by_role, project_references, mode):
	"""Assign selected image references to shots when the planner omits them."""
	image_references = []
	for row in project.selected_media or []:
		if not row.reference_key or not row.asset_version:
			continue
		media_asset = frappe.db.get_value(
			"Asset Version", row.asset_version, "media_asset"
		)
		if media_asset and frappe.db.get_value("Media Asset", media_asset, "media_type") == "Image":
			image_references.append(row)
	if not image_references:
		return

	reference_mode = getattr(settings, "reference_mode", None) or "Single Image"
	product_role = "product_reference" if "product_reference" in contract_by_role else None
	first_frame_role = next(
		(
			role for role, contract in contract_by_role.items()
			if contract.get("min_count") and contract.get("max_count") == 1
		),
		"first_frame",
	)
	for shot in plan["shots"]:
		if mode == "Continuous" and shot["shot_number"] != 1:
			continue
		references = shot.setdefault("references", [])
		role_counts = {}
		for reference in references:
			role = frappe.scrub(reference.get("usage_role") or "")
			role_counts[role] = role_counts.get(role, 0) + 1
		for role, contract in contract_by_role.items():
			needed = max(0, int(contract.get("min_count") or 0) - role_counts.get(role, 0))
			if not needed:
				continue
			if role == product_role and reference_mode == "Multi-reference" and len(image_references) < 2:
				frappe.throw(_("Multi-reference mode requires at least two selected image references."))
			for offset in range(needed):
				row = image_references[(shot["shot_number"] - 1 + offset) % len(image_references)]
				references.append({"reference_key": row.reference_key, "usage_role": role})
			role_counts[role] = role_counts.get(role, 0) + needed


def append_video_plan(
	media_project_name: str = None,
	plan: dict = None,
	start_after_shot_number: int = 0,
):
	"""Append only new Shot documents without replacing the existing storyboard."""
	project = frappe.get_doc("Media Project", media_project_name)
	from joymedia.joymedia.doctype.media_project.media_project import _project_settings

	settings = _project_settings(project)
	_validate_plan_shape(plan)
	mode = {"Independent": "Multi-shot", "Chained": "Continuous", "Consistency": "Continuous"}.get(
		settings.generation_mode, settings.generation_mode or "Multi-shot"
	)
	if mode not in ("Multi-shot", "Continuous"):
		frappe.throw(_("Select Continuous or Multi-shot generation mode."))
	workflow_contract = None
	if settings.workflow:
		from joymedia.services.workflow_resolver import get_workflow_input_contract
		workflow_contract = get_workflow_input_contract(frappe.get_doc("Generation Workflow", settings.workflow))
	contract_by_role = {item["role"]: item for item in (workflow_contract or [])}
	project_references = {
		getattr(row, "reference_key", None): row
		for row in project.selected_media or []
		if getattr(row, "reference_key", None)
	}
	base_shot_number = int(start_after_shot_number or 0)

	created_shots = []
	for offset, shot in enumerate(plan["shots"], start=1):
		for reference in shot.get("references") or []:
			key = reference["reference_key"]
			project_reference = project_references.get(key)
			if not project_reference or not project_reference.asset_version:
				frappe.throw(_("Unknown Project Reference key '{0}'.").format(key))
			role = frappe.scrub(reference.get("usage_role") or "general")
			contract = contract_by_role.get(role)
			if workflow_contract is not None and not contract:
				frappe.throw(_("Workflow does not support Shot Reference role '{0}'.").format(role))
			if contract and contract["accepted_media_type"] != "Any":
				media_type = frappe.db.get_value(
					"Media Asset",
					frappe.db.get_value("Asset Version", project_reference.asset_version, "media_asset"),
					"media_type",
				)
				if media_type != contract["accepted_media_type"]:
					frappe.throw(
						_("Workflow input role '{0}' accepts {1} media, not {2}.").format(
							role, contract["accepted_media_type"], media_type or "unknown"
						)
					)

		doc = frappe.get_doc(
			{
				"doctype": "Shot",
				"media_project": project.name,
				"shot_number": base_shot_number + offset,
				"shot_name": shot.get("shot_name") or f"Shot {base_shot_number + offset}",
				"generation_prompt": shot["generation_prompt"],
				"duration_seconds": float(shot["duration_seconds"]),
				"planned_frame_count": int(shot.get("planned_frame_count") or 0),
			}
		)
		for reference in shot.get("references") or []:
			project_reference = project_references[reference["reference_key"]]
			doc.append(
				"generation_inputs",
				{
					"reference_role": frappe.scrub(reference.get("usage_role") or "general"),
					"asset_version": project_reference.asset_version,
				},
			)
		doc.insert(ignore_permissions=True)
		created_shots.append(doc.name)

	return created_shots


def _validate_plan_shape(plan):
	if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list) or not plan["shots"]:
		frappe.throw(_("Video plan must contain a non-empty shots list."))
	seen_numbers = set()
	for shot in plan["shots"]:
		if not isinstance(shot, dict):
			frappe.throw(_("Every video plan shot must be an object."))
		shot_number = shot.get("shot_number")
		prompt = str(shot.get("generation_prompt") or "").strip()
		if type(shot_number) is not int or shot_number < 1:
			frappe.throw(_("Every video plan shot must have a positive integer shot_number."))
		if shot_number in seen_numbers:
			frappe.throw(_("Video plan contains duplicate shot numbers."))
		if not prompt:
			frappe.throw(_("Every video plan shot must have a non-empty generation_prompt."))
		seen_numbers.add(shot_number)
		references = shot.get("references") or []
		if not isinstance(references, list):
			frappe.throw(_("Shot references must be a list."))
		for reference in references:
			if not isinstance(reference, dict) or not str(reference.get("reference_key") or "").strip():
				frappe.throw(_("Every Shot Reference must contain a reference_key."))
			role = frappe.scrub(reference.get("usage_role") or "")
			if not role:
				frappe.throw(_("Every Shot Reference must contain a usage_role."))
		try:
			if float(shot["duration_seconds"]) <= 0:
				raise ValueError
		except (KeyError, TypeError, ValueError):
			frappe.throw(_("Every video plan shot must have a positive duration_seconds."))
