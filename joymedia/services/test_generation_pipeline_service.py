from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from joymedia.services.generation_pipeline_service import pipeline_for_final_workflow


class TestGenerationPipelineService(FrappeTestCase):
	def test_only_explicitly_promoted_pipeline_is_returned(self):
		pipelines = {
			"PIPE-CANDIDATE": SimpleNamespace(name="PIPE-CANDIDATE", steps=[SimpleNamespace(workflow="WF-FINAL")]),
			"PIPE-PRODUCTION": SimpleNamespace(name="PIPE-PRODUCTION", steps=[SimpleNamespace(workflow="WF-FINAL")]),
		}
		with patch("joymedia.services.generation_pipeline_service.frappe.conf", {"joymedia_active_generation_pipeline": "PIPE-PRODUCTION"}), patch(
			"joymedia.services.generation_pipeline_service.frappe.db.exists", return_value=True
		), patch("joymedia.services.generation_pipeline_service.frappe.get_doc", side_effect=lambda _doctype, name: pipelines[name]), patch(
			"joymedia.services.generation_pipeline_service.get_pipeline_steps", return_value=pipelines["PIPE-PRODUCTION"].steps
		):
			self.assertEqual("PIPE-PRODUCTION", pipeline_for_final_workflow("WF-FINAL").name)
