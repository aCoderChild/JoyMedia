from collections import defaultdict
from math import ceil

import frappe
from frappe.utils import add_days, flt, get_datetime, getdate


TERMINAL_REVIEW_STATUSES = {"Approved", "Rejected", "Needs Revision"}


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
			"output_asset_version",
			"retry_of",
			"retry_reason",
			"failure_class",
			"comfyui_worker",
			"runtime_seconds",
			"queued_at",
			"started_at",
			"gpu_cost_per_hour",
		],
	)
	job_names = {attempt.generation_job for attempt in attempts if attempt.generation_job}
	jobs = frappe.get_all(
		"Generation Job",
		filters={"name": ["in", list(job_names)]} if job_names else {"name": ["in", [""]]},
		fields=["name", "workflow_version", "compiled_prompt", "shot_specification"],
	)
	jobs_by_name = {job.name: job for job in jobs}
	prompt_names = {job.compiled_prompt for job in jobs if job.compiled_prompt}
	prompts = frappe.get_all(
		"Compiled Prompt",
		filters={"name": ["in", list(prompt_names)]} if prompt_names else {"name": ["in", [""]]},
		fields=["name", "prompt_template_version"],
	)
	prompts_by_name = {prompt.name: prompt for prompt in prompts}
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
	artifact_names = {
		artifact.name
		for artifact in frappe.get_all(
			"Generation Artifact",
			filters={"generation_attempt": ["in", attempt_names]} if attempt_names else {"name": ["in", [""]]},
			fields=["name"],
		)
	}
	reviews = frappe.get_all(
		"Quality Review",
		filters={"generation_artifact": ["in", list(artifact_names)]}
		if artifact_names
		else {"name": ["in", [""]]},
		fields=["generation_artifact", "status", "failure_class"],
	)
	artifact_attempts = frappe.get_all(
		"Generation Artifact",
		filters={"name": ["in", list(artifact_names)]} if artifact_names else {"name": ["in", [""]]},
		fields=["name", "generation_attempt"],
	)
	attempt_by_artifact = {artifact.name: artifact.generation_attempt for artifact in artifact_attempts}
	review_outcomes = defaultdict(lambda: {"approved": False, "reviewed": False})
	for review in reviews:
		attempt_name = attempt_by_artifact.get(review.generation_artifact)
		if not attempt_name:
			continue
		outcome = review_outcomes[attempt_name]
		outcome["approved"] = outcome["approved"] or review.status == "Approved"
		outcome["reviewed"] = outcome["reviewed"] or review.status in TERMINAL_REVIEW_STATUSES

	enriched_attempts = []
	for attempt in attempts:
		job = jobs_by_name.get(attempt.generation_job)
		prompt = prompts_by_name.get(job.compiled_prompt) if job else None
		attempt.workflow_version = job.workflow_version if job else None
		attempt.prompt_template_version = prompt.prompt_template_version if prompt else None
		attempt.review_outcome = review_outcomes[attempt.name]
		attempt.selected_output = bool(
			job
			and attempt.output_asset_version
			and attempt.review_outcome["approved"]
			and selected_outputs_by_shot.get(job.shot_specification) == attempt.output_asset_version
		)
		if filters.workflow_version and attempt.workflow_version != filters.workflow_version:
			continue
		if filters.prompt_template_version and attempt.prompt_template_version != filters.prompt_template_version:
			continue
		enriched_attempts.append(attempt)

	return enriched_attempts, reviews


def percentile_95(values):
	values = sorted(value for value in values if value is not None)
	if not values:
		return None
	return values[ceil(len(values) * 0.95) - 1]


def queue_wait_seconds(attempt):
	if not attempt.queued_at or not attempt.started_at:
		return None
	return max(0, (get_datetime(attempt.started_at) - get_datetime(attempt.queued_at)).total_seconds())


def estimated_cost(attempt):
	runtime_seconds = flt(attempt.runtime_seconds)
	cost_per_hour = flt(attempt.gpu_cost_per_hour)
	if not runtime_seconds or not cost_per_hour:
		return None
	return runtime_seconds / 3600 * cost_per_hour


def percent(numerator, denominator):
	return round(numerator / denominator * 100, 2) if denominator else None
