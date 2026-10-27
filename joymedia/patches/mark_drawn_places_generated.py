"""Settings the system drew were saved as uploads, so they flooded the Library.

Mark those Asset Versions as generated, like every other AI output. Projects keep
referencing them; only the Library view (which lists what people supplied) changes.
"""

import frappe


def execute():
	versions = frappe.db.sql(
		"""select v.name from `tabAsset Version` v
		join `tabMedia Asset` a on a.name = v.media_asset
		where v.source = 'Uploaded' and a.asset_category = 'Background'
		and (v.file like '/private/files/location\\_%%.png' or v.file like '/private/files/location-%%.png')""",
		pluck="name",
	)
	for name in versions:
		frappe.db.set_value("Asset Version", name, "source", "Generated", update_modified=False)
