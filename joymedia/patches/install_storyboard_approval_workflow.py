"""Install the Storyboard Approval workflow on Media Project.

The storyboard has always had Draft / Ready for Review / Approved states in `storyboard_approval_status`.
Making them a Frappe Workflow gives the desk its action buttons, role-gated transitions, and the standard
Workflow Action audit trail, with no change to the field or to the code that reads it. The transitions cover
every move the application itself makes (the controller sets Ready for Review whenever an approved plan
changes), so existing flows are unaffected.
"""

import frappe

WORKFLOW = "Storyboard Approval"
ROLES = ("JoyMedia User", "JoyMedia Specialist", "System Manager")
STATES = (("Draft", "Warning"), ("Ready for Review", "Primary"), ("Approved", "Success"))
TRANSITIONS = (
	("Draft", "Submit for review", "Ready for Review"),
	("Draft", "Approve", "Approved"),
	("Ready for Review", "Approve", "Approved"),
	("Ready for Review", "Return to draft", "Draft"),
	("Approved", "Request changes", "Ready for Review"),
)


def execute():
	if frappe.db.exists("Workflow", WORKFLOW):
		return
	for state, style in STATES:
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state, "style": style}).insert(ignore_permissions=True)
	for action in {action for _, action, _ in TRANSITIONS}:
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc({"doctype": "Workflow Action Master", "workflow_action_name": action}).insert(ignore_permissions=True)
	workflow = frappe.get_doc({
		"doctype": "Workflow",
		"workflow_name": WORKFLOW,
		"document_type": "Media Project",
		"workflow_state_field": "storyboard_approval_status",
		"is_active": 1,
		"send_email_alert": 0,
		"states": [
			{"state": state, "doc_status": "0", "allow_edit": role} for state, _ in STATES for role in ROLES
		],
		"transitions": [
			{"state": state, "action": action, "next_state": next_state, "allowed": role, "allow_self_approval": 1}
			for state, action, next_state in TRANSITIONS for role in ROLES
		],
	})
	workflow.insert(ignore_permissions=True)
