import frappe


def ensure_home_folder_exists(doc, method=None):
	from joymedia.services.partners import is_reviewer, require_generation

	if is_reviewer():
		require_generation()
	if doc.is_home_folder:
		return
	if doc.folder != "Home":
		return
	if frappe.db.exists("File", {"is_home_folder": 1}):
		return
	from frappe.core.doctype.file.utils import make_home_folder

	make_home_folder()
