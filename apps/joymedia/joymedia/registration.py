import frappe
from frappe import _


def get_signup_template():
	return "joymedia/templates/signup.html"


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_with_organization(email, full_name, organization_name, password=None, redirect_to=None):
	organization_name = (organization_name or "").strip()
	if not organization_name:
		frappe.throw(_("Business / Organization name is required."))
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

	organization_name_id = frappe.db.get_value(
		"Client Organization", {"organization_name": organization_name}, "name"
	)
	organization = (
		frappe.get_doc("Client Organization", organization_name_id)
		if organization_name_id
		else frappe.get_doc(
			{
				"doctype": "Client Organization",
				"organization_name": organization_name,
			}
		).insert(ignore_permissions=True)
	)

	if not any(role.role == "JoyMedia User" for role in user.roles):
		user.append("roles", {"role": "JoyMedia User"})
		user.save(ignore_permissions=True)

	frappe.get_doc(
		{
			"doctype": "User Permission",
			"user": user_name,
			"allow": "Client Organization",
			"for_value": organization.name,
			"is_default": 1,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	frappe.local.login_manager.login_as(user_name)

	return {
		"status": 1,
		"message": _("Account created."),
		"organization": organization.name,
		"redirect_url": "/joymedia/campaigns",
	}
