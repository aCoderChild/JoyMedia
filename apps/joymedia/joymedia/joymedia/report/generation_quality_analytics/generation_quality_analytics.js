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
		{
			fieldname: "prompt_template_version",
			label: "Prompt Template Version",
			fieldtype: "Link",
			options: "Prompt Template Version",
		},
	],
};
