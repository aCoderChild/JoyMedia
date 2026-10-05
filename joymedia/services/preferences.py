"""Per-user preferences of the JoyMedia studio."""

import frappe
from frappe import _

SUPPORTED_LANGUAGES = ("vi", "en")


@frappe.whitelist()
def set_language(language):
	"""Use the studio's language for the user's server messages (errors, notices) too."""
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be signed in to change the language."))
	if language not in SUPPORTED_LANGUAGES:
		frappe.throw(_("Unsupported language."))
	if frappe.db.get_value("User", frappe.session.user, "language") != language:
		frappe.db.set_value("User", frappe.session.user, "language", language)
	return {"language": language}
