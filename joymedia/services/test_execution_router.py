from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from joymedia.services.execution_router import select_worker


class TestExecutionRouter(FrappeTestCase):
	@patch("joymedia.services.execution_router.get_model_cache_key", return_value="minimax-h3")
	@patch("joymedia.services.execution_router.frappe.get_all")
	def test_prefers_worker_with_matching_model_cache_key(self, get_all, get_model_cache_key):
		get_all.side_effect = [
			[
				{
					"name": "CUIW-00001",
					"endpoint_url": "http://h3-worker:8188",
					"input_dir": "/srv/comfy/input",
					"model_cache_key": "minimax-h3",
				}
			],
		]

		worker = select_worker("WFV-00001")

		self.assertEqual(worker.name, "CUIW-00001")
		get_model_cache_key.assert_called_once_with("WFV-00001")
		get_all.assert_called_once_with(
			"ComfyUI Worker",
			filters={"status": "Active", "model_cache_key": "minimax-h3"},
			fields=["name", "endpoint_url", "input_dir", "model_cache_key"],
			order_by="routing_priority asc, name asc",
			limit_page_length=1,
		)

	@patch("joymedia.services.execution_router.get_model_cache_key", return_value="minimax-h3")
	@patch("joymedia.services.execution_router.frappe.get_all")
	def test_uses_general_purpose_worker_only_when_no_matching_worker(self, get_all, _get_model_cache_key):
		get_all.side_effect = [
			[],
			[
				{
					"name": "CUIW-00002",
					"endpoint_url": "http://general-worker:8188",
					"input_dir": "",
					"model_cache_key": "",
				}
			],
		]

		worker = select_worker("WFV-00001")

		self.assertEqual(worker.name, "CUIW-00002")
