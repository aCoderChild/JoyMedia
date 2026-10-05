"""Plan the storyboard and start rendering in the background.

Image analysis and the AI director together take one to three minutes, longer
than a web request may run in production, so the Generate button only queues
this job and the studio polls the project's planning_status.
"""

import frappe
from frappe import _

from joymedia.services.render_queue import is_render_alive


def queue_storyboard(project_name):
	"""Queue planning + rendering for a project with no storyboard yet."""
	if planning_status(project_name) == "Running":
		return {"status": "Planning"}
	_set(project_name, "Running", "")
	frappe.enqueue(
		"joymedia.services.storyboard_job.plan_and_generate",
		queue="long",
		timeout=1800,
		job_id=_job_id(project_name),
		deduplicate=True,
		enqueue_after_commit=True,
		project_name=project_name,
	)
	frappe.db.commit()
	return {"status": "Planning"}


def planning_status(project_name):
	"""The project's planning status; a planning job that died is reported as Failed."""
	status = frappe.db.get_value("Media Project", project_name, "planning_status") or "Idle"
	if status == "Running" and not is_render_alive(_job_id(project_name)):
		_set(project_name, "Failed", _("Creating the storyboard stopped unexpectedly. Please try again."))
		return "Failed"
	return status


def plan_and_generate(project_name):
	from joymedia.services.shot_duration_planner import recalculate_shot_durations
	from joymedia.services.video_plan_service import apply_video_plan

	try:
		project = frappe.get_doc("Media Project", project_name)
		if not frappe.db.exists("Shot", {"media_project": project.name, "is_removed": 0}):
			project._use_reference_video_for_story_film()
			plan = project.generate_video_plan()
			# Planning takes minutes; start a fresh transaction so MariaDB's snapshot
			# isolation does not reject writes to rows changed meanwhile.
			frappe.db.commit()
			apply_video_plan(project.name, plan)
			recalculate_shot_durations(project.name)
			frappe.db.commit()
			project.reload()
		project.generate_video()
		_set(project_name, "Idle", "")
	except Exception as exc:
		frappe.db.rollback()
		frappe.log_error(title=f"Storyboard planning failed for {project_name}")
		# Validation messages ("Add at least one image…") are written for users; anything
		# else is a technical failure the Error Log keeps.
		message = str(exc) if isinstance(exc, frappe.ValidationError) else _(
			"The AI director could not create the storyboard. Please try again."
		)
		_set(project_name, "Failed", message[:1000])


def _set(project_name, status, error):
	frappe.db.set_value(
		"Media Project", project_name, {"planning_status": status, "planning_error": error}, update_modified=False
	)
	frappe.db.commit()


def _job_id(project_name):
	return f"joymedia:storyboard:{project_name}"
