import frappe
from frappe import _
from frappe.model.document import Document


class PartnerAccess(Document):
	def validate(self):
		from joymedia.services.partners import ROLE, published_target

		if self.is_new():
			self.model_jobs_used = 0
		else:
			current = frappe.db.sql(
				"select user, model_jobs_used from `tabPartner Access` where name=%s for update",
				self.name,
				as_dict=True,
			)[0]
			if current.user != self.user:
				frappe.throw(_("Create a separate access record for another partner account."))
			# A grant form may have been opened before a worker charged another job.
			# Never let saving that form overwrite the authoritative usage counter.
			self.model_jobs_used = current.model_jobs_used

		if (
			self.user in ("Guest", "Administrator")
			or "System Manager" in frappe.get_roles(self.user)
			or "JoyMedia Specialist" in frappe.get_roles(self.user)
			or "JoyMedia User" in frappe.get_roles(self.user)
		):
			frappe.throw(_("Choose a partner account without administrator, production or client roles."))
		if frappe.db.get_value("User", self.user, "user_type") != "Website User":
			frappe.throw(_("Partner reviewer accounts must be Website Users."))
		if self.enabled and not frappe.db.get_value("User", self.user, "enabled"):
			frappe.throw(_("Enable the partner User account first."))
		for key in ("max_projects", "max_model_jobs", "max_duration_seconds", "max_pixels"):
			if int(self.get(key) or 0) <= 0:
				frappe.throw(_("Set positive testing limits."))
		if self.max_model_jobs < (self.model_jobs_used or 0):
			frappe.throw(_("The model-job limit cannot be below usage already recorded."))
		seen = set()
		for row in self.videos:
			published_target(row.asset_version)
			row.label = (row.label or "").strip()
			if not row.label or row.asset_version in seen:
				frappe.throw(_("Give each published version a title and list it only once."))
			seen.add(row.asset_version)

	def on_update(self):
		from joymedia.services.partners import ROLE

		user = frappe.get_doc("User", self.user)
		if ROLE not in {row.role for row in user.roles}:
			user.add_roles(ROLE)
