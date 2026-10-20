"""One role vocabulary for the portal; document permissions remain authoritative."""

import frappe
from frappe import _

REVIEWER = "JoyMedia Reviewer"
INTERNAL_ROLES = {"System Manager", "JoyMedia Specialist", "JoyMedia User"}


def role_for(user, roles):
	roles = set(roles)
	if user == "Guest":
		return "unassigned"
	# A reviewer with conflicting roles fails closed, including legacy assignments.
	if REVIEWER in roles and roles.intersection(INTERNAL_ROLES):
		return "unassigned"
	if user == "Administrator" or "System Manager" in roles:
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
