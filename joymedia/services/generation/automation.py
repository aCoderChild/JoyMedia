"""Request-scoped automatic delivery; existing runs keep their frozen policy."""

from contextlib import contextmanager
from contextvars import ContextVar

_delivery = ContextVar("joymedia_automatic_delivery", default=None)


def is_automatic(request):
	return request.get("delivery_mode") == "automatic"


def current_delivery():
	return _delivery.get()


def screened_preview_report(report):
	"""Only the generic certification caveat may remain on a screened preview.

	This authorizes a provisional workflow handoff, not a visual or physics pass.
	Observed defects and missing/uncertain observations are never waived.
	"""
	if not report or report.get("status") != "Needs Review" or report.get("review_only") is not True:
		return False
	rows = report.get("results") or []
	ids = [r.get("id") for r in rows]
	required = set(report.get("required_claim_ids") or [])
	if (
		not rows
		or len(set(ids)) != len(ids)
		or not required.issubset(set(ids))
		or not {"cast_inventory", "active_canvas", "geometry_qualification"}.issubset(required)
	):
		return False
	return all(
		r.get("verdict") == ("uncertain" if r.get("id") == "geometry_qualification" else "supported")
		and bool(str(r.get("reason") or "").strip())
		for r in rows
	)


def advance_automatic_run(run_name):
	"""Use the native dispatcher without waiting behind unrelated visual checks.

	Its existing global capacity, fairness, cancellation and per-attempt locks still
	apply. Older runs without the explicit frozen mode retain their own processing.
	"""
	import frappe

	from joymedia.services.generation.orchestrator import refresh_run, submit_run

	row = frappe.db.get_value("Generation Run", run_name, ["status", "project_snapshot_json"], as_dict=True)
	if not row or row.status not in {"Queued", "Running"}:
		return
	if not (frappe.parse_json(row.project_snapshot_json or "{}") or {}).get("automatic_delivery"):
		return
	refresh_run(run_name)
	submit_run(run_name)


@contextmanager
def delivery_context(request, batch=None):
	"""Authorize intermediate outputs without claiming a human or machine pass.

	The mode is frozen in the next run snapshot. It never changes site settings,
	previous snapshots, admission reports, or final release approval.
	"""
	policy = (
		{"mode": "automatic", "batch": batch, "quality_review": "required", "export_purpose": "review"}
		if is_automatic(request)
		else None
	)
	token = _delivery.set(policy)
	try:
		yield
	finally:
		_delivery.reset(token)
