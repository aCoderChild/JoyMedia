frappe.query_reports["Generation Quality Analytics"] = {
	filters: [
		{ fieldname: "from_date", label: "From Date", fieldtype: "Date" },
		{ fieldname: "to_date", label: "To Date", fieldtype: "Date" },
		{
			fieldname: "workflow_version",
			label: "Workflow Version",
			fieldtype: "Link",
			options: "Workflow Version",
		},
	],
};
