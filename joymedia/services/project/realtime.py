"""Push project changes to open studios through Frappe's realtime (socket.io) layer.

Events go to the project's document room, so only people allowed to read the project receive them
and the studio can refresh instantly instead of polling.
"""

import frappe

PROJECT_UPDATED = "joymedia_project_updated"
PLANNING_PROGRESS = "joymedia_planning_progress"


def publish_project_event(project_name, event, payload=None, after_commit=True):
	"""Publish to the project's document room.

	`after_commit=True` (the default) holds the message until the transaction commits, which is right
	when clients will reload saved data. Progress of a long background job must pass False: in a job
	the commit only happens at the very end, so held messages would all arrive in one burst.
	"""
	if not project_name:
		return
	frappe.publish_realtime(
		event, {"project": project_name, **(payload or {})}, doctype="Media Project", docname=project_name,
		after_commit=after_commit,
	)


def project_changed(doc, method=None):
	"""doc_events hook: a Media Project changed."""
	publish_project_event(doc.name, PROJECT_UPDATED, {"doctype": "Media Project"})


def shot_changed(doc, method=None):
	"""doc_events hook: a Shot of a project changed."""
	publish_project_event(doc.media_project, PROJECT_UPDATED, {"doctype": "Shot", "shot": doc.name})
