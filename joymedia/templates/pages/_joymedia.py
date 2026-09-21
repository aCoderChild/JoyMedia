import frappe


no_cache = 1


def get_context():
	return {
		"csrf_token": frappe.sessions.get_csrf_token(),
		"site_name": frappe.local.site,
		"lang": frappe.local.lang,
		"user": frappe.session.user,
	}
