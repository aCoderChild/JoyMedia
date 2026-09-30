import frappe


def execute():
	"""Copy Campaign context onto Media Project before the Campaign model is removed."""
	if not frappe.db.table_exists("Media Project") or not frappe.db.table_exists("Campaign"):
		return

	columns = {
		row[0]
		for row in frappe.db.sql("SHOW COLUMNS FROM `tabMedia Project`", as_list=True)
	}
	if "product_name" not in columns:
		frappe.db.sql("ALTER TABLE `tabMedia Project` ADD COLUMN `product_name` varchar(140)")
	if "campaign_brief" not in columns:
		frappe.db.sql("ALTER TABLE `tabMedia Project` ADD COLUMN `campaign_brief` text")

	frappe.db.sql(
		"""
		UPDATE `tabMedia Project` project
		INNER JOIN `tabCampaign` campaign ON campaign.name = project.campaign
		SET
			project.project_name = COALESCE(NULLIF(campaign.campaign_name, ''), project.project_name),
			project.product_name = campaign.product_name,
			project.campaign_brief = campaign.campaign_brief
		WHERE project.campaign IS NOT NULL AND project.campaign != ''
		"""
	)

	if frappe.db.exists("DocType", "Campaign"):
		frappe.delete_doc("DocType", "Campaign", ignore_permissions=True, force=True)
