"""Background queue for long GPU renders (export finishing, Finish film).

These jobs run for up to an hour. On the shared "long" queue they would hold the
worker that also starts generation runs, so they go to a dedicated queue when a
worker serves it (configure `workers: {"joymedia_render": {"timeout": 10800}}`
in common_site_config.json and run `bench worker --queue joymedia_render`).
"""

import frappe
from frappe.utils.background_jobs import get_queue, get_queues_timeout, get_workers, is_job_enqueued

RENDER_QUEUE = "joymedia_render"


def enqueue_render(method, job_id, timeout, **kwargs):
	frappe.enqueue(
		method,
		queue=_render_queue(),
		timeout=timeout,
		job_id=job_id,
		deduplicate=True,
		enqueue_after_commit=True,
		**kwargs,
	)


def is_render_alive(job_id):
	"""Whether the background job is still queued or running.

	A job killed by a worker restart or timeout never reports back, so its
	"Running" status would otherwise block the button forever.
	"""
	return is_job_enqueued(job_id)


def _render_queue():
	if RENDER_QUEUE in get_queues_timeout() and get_workers(get_queue(RENDER_QUEUE)):
		return RENDER_QUEUE
	return "long"
