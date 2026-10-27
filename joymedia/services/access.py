"""One role vocabulary for the portal; document permissions remain authoritative."""

import frappe
from frappe import _

REVIEWER = "JoyMedia Reviewer"
INTERNAL_ROLES = {"System Manager", "JoyMedia Specialist", "JoyMedia User"}


def role_for(user, roles):
	roles = set(roles)
	if user == "Guest":
		return "unassigned"
	# Frappe gives the built-in Administrator every role, the reviewer role included;
	# the conflict rule below is for accounts assigned both roles by mistake.
	if user == "Administrator":
		return "administrator"
	# A reviewer with conflicting roles fails closed, including legacy assignments.
	if REVIEWER in roles and roles.intersection(INTERNAL_ROLES):
		return "unassigned"
	if "System Manager" in roles:
		return "administrator"
	if REVIEWER in roles:
		return "reviewer"
	if "JoyMedia Specialist" in roles:
		return "production"
	if "JoyMedia User" in roles:
		return "client"
	return "unassigned"


def portal_access(user=None):
	user = user or frappe.session.user
	role = role_for(user, frappe.get_roles(user))
	technical = role in ("administrator", "production")
	return {
		"role": role,
		"administrator": role == "administrator",
		"reviewer": role == "reviewer",
		"can_create": role in ("administrator", "production", "client"),
		"can_use_library": technical,
		"can_use_advanced_editor": technical,
		"can_manage_reviewers": role == "administrator",
	}


def validate_user_roles(doc, method=None):
	roles = {row.role for row in doc.roles}
	if REVIEWER in roles and roles.intersection(INTERNAL_ROLES):
		frappe.throw(
			_(
				"Reviewer accounts cannot also be administrators, production team members or clients. Use a separate account."
			)
		)


# Render outputs (held clips a person must review) are readable exactly where their project is.
_ARTIFACT_PROJECT = """select coalesce(r.media_project, s.media_project)
	from `tabGeneration Attempt` a
	join `tabGeneration Task` t on t.name = a.generation_task
	left join `tabGeneration Run` r on r.name = t.generation_run
	left join `tabShot` s on s.name = t.shot
	where a.name = %s"""


def _sees_all_renders(user):
	return user == "Administrator" or bool(
		{"System Manager", "JoyMedia Specialist"} & set(frappe.get_roles(user))
	)


def artifact_permission(doc, user=None, permission_type=None, ptype=None, debug=False):
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user) or user == "Administrator":
		return True
	if (permission_type or ptype or "read") != "read":
		return False
	row = frappe.db.sql(_ARTIFACT_PROJECT, doc.generation_attempt)
	project = row[0][0] if row else None
	return bool(project) and frappe.has_permission("Media Project", "read", doc=project, user=user)


def artifact_query(user=None):
	user = user or frappe.session.user
	if _sees_all_renders(user):
		return ""
	escaped = frappe.db.escape(user)
	return f"""`tabGeneration Artifact`.generation_attempt in (select a.name
		from `tabGeneration Attempt` a
		join `tabGeneration Task` t on t.name = a.generation_task
		left join `tabGeneration Run` r on r.name = t.generation_run
		left join `tabShot` s on s.name = t.shot
		join `tabMedia Project` p on p.name = coalesce(r.media_project, s.media_project)
		where p.owner = {escaped})"""
