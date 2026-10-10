from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation_pipeline_service import pipeline_for_final_workflow


class TestGenerationPipelineService(FrappeTestCase):
	def test_candidate_pipeline_does_not_replace_existing_default(self):
		rows = [
			SimpleNamespace(name="PIPE-CANDIDATE", pipeline_key="flux2_h3_i2v_candidate"),
			SimpleNamespace(name="PIPE-PRODUCTION", pipeline_key="flux_h3_i2v_production"),
		]
		pipelines = {
			"PIPE-CANDIDATE": SimpleNamespace(name="PIPE-CANDIDATE", steps=[SimpleNamespace(workflow="WF-FINAL")]),
			"PIPE-PRODUCTION": SimpleNamespace(name="PIPE-PRODUCTION", steps=[SimpleNamespace(workflow="WF-FINAL")]),
		}
		with patch("joymedia.services.generation_pipeline_service.frappe.get_all", return_value=rows), patch(
			"joymedia.services.generation_pipeline_service.frappe.get_doc",
			side_effect=lambda _doctype, name: pipelines[name],
		):
			self.assertEqual("PIPE-PRODUCTION", pipeline_for_final_workflow("WF-FINAL").name)
