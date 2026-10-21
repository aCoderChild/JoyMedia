from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from joymedia.services.workflows.pipeline import pipeline_for_final_workflow


class TestGenerationPipelineService(FrappeTestCase):
	def test_persisted_derived_profile_coexists_with_operator_site_pins(self):
		from contextlib import nullcontext

		import frappe

		from joymedia.services.workflows.pipeline import get_pinned_generation_pipeline, persist_execution_pin

		stored = {"existing": "PIPE-EXISTING"}

		def save(key, value):
			stored.clear()
			stored.update(frappe.parse_json(value))

		with (
			patch(
				"joymedia.services.workflows.pipeline.frappe.conf",
				{"joymedia_project_generation_pipelines": {"source": "PIPE-OPERATOR"}},
			),
			patch(
				"joymedia.services.workflows.pipeline.frappe.defaults.get_global_default",
				side_effect=lambda key: frappe.as_json(stored),
			),
			patch(
				"joymedia.services.workflows.pipeline.frappe.defaults.set_global_default", side_effect=save
			),
			patch("joymedia.services.workflows.pipeline.frappe.cache.lock", return_value=nullcontext()),
			patch("joymedia.services.workflows.pipeline.frappe.db.commit"),
			patch("joymedia.services.workflows.pipeline.frappe.db.exists", return_value=True),
			patch(
				"joymedia.services.workflows.pipeline.frappe.get_doc",
				side_effect=lambda kind, name: SimpleNamespace(name=name),
			),
			patch("joymedia.services.workflows.pipeline.get_pipeline_steps"),
		):
			persist_execution_pin("derived", "PIPE-FROZEN")
			self.assertEqual("PIPE-FROZEN", get_pinned_generation_pipeline("derived").name)
			self.assertEqual("PIPE-OPERATOR", get_pinned_generation_pipeline("source").name)
			self.assertEqual("PIPE-EXISTING", get_pinned_generation_pipeline("existing").name)

	def test_only_explicitly_promoted_pipeline_is_returned(self):
		pipelines = {
			"PIPE-CANDIDATE": SimpleNamespace(
				name="PIPE-CANDIDATE", steps=[SimpleNamespace(workflow="WF-FINAL")]
			),
			"PIPE-PRODUCTION": SimpleNamespace(
				name="PIPE-PRODUCTION", steps=[SimpleNamespace(workflow="WF-FINAL")]
			),
		}
		with (
			patch(
				"joymedia.services.workflows.pipeline.frappe.conf",
				{"joymedia_active_generation_pipeline": "PIPE-PRODUCTION"},
			),
			patch("joymedia.services.workflows.pipeline.frappe.db.exists", return_value=True),
			patch(
				"joymedia.services.workflows.pipeline.frappe.get_doc",
				side_effect=lambda _doctype, name: pipelines[name],
			),
			patch(
				"joymedia.services.workflows.pipeline.get_pipeline_steps",
				return_value=pipelines["PIPE-PRODUCTION"].steps,
			),
		):
			self.assertEqual("PIPE-PRODUCTION", pipeline_for_final_workflow("WF-FINAL").name)

	def test_durable_execution_pin_survives_native_default_lookup_and_is_scoped(self):
		import frappe

		from joymedia.services.workflows.pipeline import get_pinned_generation_pipeline, pinned_execution

		before = frappe.flags.get("joymedia_execution_pipelines")
		with (
			patch(
				"joymedia.services.workflows.pipeline.frappe.conf",
				{"joymedia_project_generation_pipelines": {}},
			),
			patch("joymedia.services.workflows.pipeline.frappe.db.exists", return_value=True),
			patch(
				"joymedia.services.workflows.pipeline.frappe.get_doc",
				side_effect=lambda kind, name: SimpleNamespace(name=name),
			),
			patch("joymedia.services.workflows.pipeline.get_pipeline_steps"),
		):
			with self.assertRaisesRegex(RuntimeError, "native operation failed"):
				with pinned_execution("derived-version", "PIPE-FROZEN"):
					self.assertEqual("PIPE-FROZEN", get_pinned_generation_pipeline("derived-version").name)
					self.assertIsNone(get_pinned_generation_pipeline("another-project"))
					with pinned_execution("derived-version", "PIPE-NESTED"):
						self.assertEqual(
							"PIPE-NESTED", get_pinned_generation_pipeline("derived-version").name
						)
					self.assertEqual("PIPE-FROZEN", get_pinned_generation_pipeline("derived-version").name)
					raise RuntimeError("native operation failed")
			self.assertIsNone(get_pinned_generation_pipeline("derived-version"))
		self.assertEqual(before, frappe.flags.get("joymedia_execution_pipelines"))
