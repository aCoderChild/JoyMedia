import frappe
from frappe import _
from frappe.rate_limiter import rate_limit


def get_signup_template():
	return "joymedia/templates/signup.html"


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60, methods="POST")
def register_user(email, full_name, password=None, redirect_to=None):
	if not frappe.conf.get("joymedia_allow_signup"):
		frappe.throw(_("Self-registration is disabled. Ask an administrator to invite you."), frappe.PermissionError)
	password = password or ""
	if len(password) < 8:
		frappe.throw(_("Password must be at least 8 characters long."))

	from frappe.core.doctype.user.user import sign_up

	result = sign_up(email=email, full_name=full_name, redirect_to=redirect_to or "")
	status = result[0]
	if status == 0:
		return {
			"status": status,
			"message": _("This email is already registered. Please sign in."),
		}

	user_name = frappe.db.get_value("User", {"email": email}, "name")
	if not user_name:
		frappe.throw(_("The account was created, but the user record could not be found."))

	user = frappe.get_doc("User", user_name)

	from frappe.utils.password import update_password
	update_password(user_name, password)
	user.db_set("reset_password_key", None, update_modified=False)

	if not any(role.role == "JoyMedia User" for role in user.roles):
		user.append("roles", {"role": "JoyMedia User"})
		user.save(ignore_permissions=True)

	frappe.local.login_manager.login_as(user_name)

	return {
		"status": 1,
		"message": _("Account created."),
		"redirect_url": "/joymedia/campaigns",
	}
