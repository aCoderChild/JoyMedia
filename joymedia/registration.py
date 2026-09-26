import frappe
from frappe import _


def get_signup_template():
	return "joymedia/templates/signup.html"


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_with_organization(email, full_name, organization_name, industry=None, redirect_to=None):
	organization_name = (organization_name or "").strip()
	if not organization_name:
		frappe.throw(_("Business / Organization name is required."))

	from frappe.core.doctype.user.user import sign_up

	result = sign_up(email=email, full_name=full_name, redirect_to=redirect_to or "")
	status = result[0]
	if status not in (1, 2):
		return {"status": status, "message": result[1]}

	user_name = frappe.db.get_value("User", {"email": email}, "name")
	if not user_name:
		frappe.throw(_("The account was created, but the user record could not be found."))

	organization = frappe.get_doc(
		{
			"doctype": "Client Organization",
			"organization_name": organization_name,
			"industry": (industry or "").strip(),
		}
	).insert(ignore_permissions=True)

	user = frappe.get_doc("User", user_name)
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

	return {"status": status, "message": result[1], "organization": organization.name}
