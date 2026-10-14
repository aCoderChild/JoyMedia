"""Helpers shared by tests."""

from unittest.mock import patch

import frappe


def without_promoted_pipeline(test_case):
	"""Make a test independent of the pipeline the site happens to have promoted.

	Tests that exercise draft planning or snapshots assume nothing is promoted; a live site always has one
	configured, which used to make them fail only there. Returns nothing; the patch ends with the test.
	"""
	patcher = patch(
		"joymedia.services.workflows.pipeline.get_active_generation_pipeline",
		side_effect=frappe.ValidationError("No active Generation Pipeline is configured."),
	)
	patcher.start()
	test_case.addCleanup(patcher.stop)
