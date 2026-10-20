import frappe

no_cache = 1


def _socket_base():
	"""Where this browser reaches Frappe's realtime server (separate port in developer mode, same origin behind nginx)."""
	if frappe.conf.developer_mode and frappe.conf.socketio_port:
		scheme = "https" if frappe.local.request.scheme == "https" else "http"
		return f"{scheme}://{frappe.local.request.host.split(':')[0]}:{frappe.conf.socketio_port}"
	return ""


def get_context():
	return {
		"csrf_token": frappe.sessions.get_csrf_token(),
		"site_name": frappe.local.site,
		"socket_base": _socket_base(),
		"lang": frappe.local.lang,
		"user": frappe.session.user,
	}
