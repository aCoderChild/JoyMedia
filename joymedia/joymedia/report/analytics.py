from math import ceil

import frappe
from frappe.utils import add_days, get_datetime, getdate


def get_attempt_analytics(filters=None):
	filters = frappe._dict(filters or {})
	attempt_filters = {}
	if filters.from_date:
		attempt_filters["creation"] = [">=", getdate(filters.from_date)]
	if filters.to_date:
		attempt_filters.setdefault("creation", ["<", add_days(getdate(filters.to_date), 1)])
		if attempt_filters["creation"][0] == ">=":
			attempt_filters["creation"] = [
				"between",
				[attempt_filters["creation"][1], add_days(getdate(filters.to_date), 1)],
			]

	attempts = frappe.get_all(
		"Generation Attempt",
		filters=attempt_filters,
		fields=[
			"name",
			"generation_job",
			"status",
			"retry_of",
			"retry_reason",
			"failure_class",
			"runtime_seconds",
			"queued_at",
			"started_at",
		],
	)
	job_names = {attempt.generation_job for attempt in attempts if attempt.generation_job}
	jobs = frappe.get_all(
		"Generation Job",
		filters={"name": ["in", list(job_names)]} if job_names else {"name": ["in", [""]]},
		fields=["name", "workflow_version", "shot_specification"],
	)
	jobs_by_name = {job.name: job for job in jobs}
	shot_names = {job.shot_specification for job in jobs if job.shot_specification}
	shots = frappe.get_all(
		"Shot Specification",
		filters={"name": ["in", list(shot_names)]} if shot_names else {"name": ["in", [""]]},
		fields=["name", "selected_output_asset_version"],
	)
	selected_outputs_by_shot = {
		shot.name: shot.selected_output_asset_version for shot in shots if shot.selected_output_asset_version
	}

	attempt_names = [attempt.name for attempt in attempts]
	artifacts = frappe.get_all(
			"Generation Artifact",
			filters={"generation_attempt": ["in", attempt_names]} if attempt_names else {"name": ["in", [""]]},
			fields=["name", "generation_attempt", "artifact_role", "frappe_file"],
		)
	primary_outputs_by_attempt = {
		artifact.generation_attempt: artifact.name
		for artifact in artifacts
		if artifact.artifact_role == "Primary Video" and artifact.frappe_file
	}
	enriched_attempts = []
	for attempt in attempts:
		job = jobs_by_name.get(attempt.generation_job)
		attempt.workflow_version = job.workflow_version if job else None
		selected = primary_outputs_by_attempt.get(attempt.name)
		attempt.review_outcome = {"approved": bool(selected), "reviewed": bool(selected)}
		attempt.selected_output = bool(
			job
			and selected
			and selected_outputs_by_shot.get(job.shot_specification) == selected
		)
		if filters.workflow_version and attempt.workflow_version != filters.workflow_version:
			continue
		enriched_attempts.append(attempt)

	return enriched_attempts, []


def percentile_95(values):
	values = sorted(value for value in values if value is not None)
	if not values:
		return None
	return values[ceil(len(values) * 0.95) - 1]


def queue_wait_seconds(attempt):
	if not attempt.queued_at or not attempt.started_at:
		return None
	return max(0, (get_datetime(attempt.started_at) - get_datetime(attempt.queued_at)).total_seconds())


def percent(numerator, denominator):
	return round(numerator / denominator * 100, 2) if denominator else None
