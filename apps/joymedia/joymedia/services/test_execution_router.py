from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.execution_router import select_worker


class TestExecutionRouter(FrappeTestCase):
	@patch("joymedia.services.execution_router.get_model_cache_key", return_value="minimax-h3")
	@patch("joymedia.services.execution_router._get_routable_workers")
	@patch("joymedia.services.execution_router.get_active_job_count")
	def test_prefers_confirmed_warm_worker_before_load(
		self, get_active_job_count, get_routable_workers, _get_model_cache_key
	):
		warm_worker = frappe._dict(
			name="CUIW-WARM",
			model_cache_key="minimax-h3",
			observed_model_cache_key="minimax-h3",
			max_concurrent_jobs=4,
			routing_priority=100,
		)
		cold_worker = frappe._dict(
			name="CUIW-COLD",
			model_cache_key="minimax-h3",
			observed_model_cache_key="",
			max_concurrent_jobs=4,
			routing_priority=1,
		)
		get_routable_workers.return_value = [warm_worker, cold_worker]
		get_active_job_count.side_effect = [2, 0]

		worker = select_worker("WFV-00001")

		self.assertEqual(worker.name, "CUIW-WARM")

	@patch("joymedia.services.execution_router.get_model_cache_key", return_value="minimax-h3")
	@patch("joymedia.services.execution_router._get_routable_workers")
	@patch("joymedia.services.execution_router.get_active_job_count")
	def test_routes_by_lowest_load_after_cache_affinity(
		self, get_active_job_count, get_routable_workers, _get_model_cache_key
	):
		first_worker = frappe._dict(
			name="CUIW-00001",
			model_cache_key="minimax-h3",
			observed_model_cache_key="minimax-h3",
			max_concurrent_jobs=4,
			routing_priority=1,
		)
		second_worker = frappe._dict(
			name="CUIW-00002",
			model_cache_key="minimax-h3",
			observed_model_cache_key="minimax-h3",
			max_concurrent_jobs=4,
			routing_priority=100,
		)
		get_routable_workers.return_value = [first_worker, second_worker]
		get_active_job_count.side_effect = [2, 1]

		worker = select_worker("WFV-00001")

		self.assertEqual(worker.name, "CUIW-00002")

	@patch("joymedia.services.execution_router.get_model_cache_key", return_value="minimax-h3")
	@patch("joymedia.services.execution_router._get_routable_workers")
	@patch("joymedia.services.execution_router.get_active_job_count", return_value=1)
	def test_does_not_route_to_a_worker_at_capacity(
		self, _get_active_job_count, get_routable_workers, _get_model_cache_key
	):
		get_routable_workers.return_value = [
			frappe._dict(
				name="CUIW-00001",
				model_cache_key="minimax-h3",
				observed_model_cache_key="minimax-h3",
				max_concurrent_jobs=1,
				routing_priority=1,
			)
		]

		self.assertIsNone(select_worker("WFV-00001"))
