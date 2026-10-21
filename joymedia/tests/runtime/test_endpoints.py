from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.services.runtime import endpoints


class TestRuntimeEndpoints(FrappeTestCase):
	def test_nonfinite_timeouts_are_rejected_before_network_calls(self):
		for timeout in [float("nan"), float("inf"), -1, 0]:
			with patch.object(
				frappe,
				"conf",
				frappe._dict(
					joymedia_vision={"base_url": "http://vision/v1", "model": "test", "timeout": timeout}
				),
			):
				# A zero follows the existing default-timeout compatibility rule.
				if timeout == 0:
					self.assertEqual(endpoints.endpoint("vision").timeout, 120)
				else:
					with self.assertRaises(frappe.ValidationError):
						endpoints.endpoint("vision")

	def test_neutral_profile_is_used_in_preference_to_legacy_keys(self):
		with patch.object(
			frappe,
			"conf",
			frappe._dict(
				{
					"joymedia_planner": {
						"base_url": "http://planner/v1/",
						"model": "configured",
						"timeout": 42,
						"max_model_len": 8192,
					},
					"qwen_base_url": "http://legacy/v1",
					"qwen_model": "legacy",
				}
			),
		):
			configured = endpoints.endpoint("planner")
			self.assertEqual("http://planner/v1", configured.base_url)
			self.assertEqual("configured", configured.model)
			self.assertEqual(42, configured.timeout)
			self.assertEqual(8192, endpoints.planner_context_window(4096))

	def test_legacy_keys_remain_a_temporary_configuration_compatibility_path(self):
		with patch.object(
			frappe,
			"conf",
			frappe._dict(
				{"qwen_vl_base_url": "http://vision/v1/", "qwen_vl_model": "vision", "qwen_vl_timeout": 15}
			),
		):
			configured = endpoints.endpoint("vision")
		self.assertEqual("http://vision/v1", configured.base_url)
		self.assertEqual("vision", configured.model)
		self.assertEqual(15, configured.timeout)

	def test_writer_can_use_general_instruction_endpoint_without_changing_production_planner(self):
		with patch.object(
			frappe,
			"conf",
			frappe._dict(
				{
					"joymedia_planner": {"base_url": "http://planner/v1", "model": "specialized"},
					"joymedia_translator": {"base_url": "http://general/v1", "model": "instruction"},
				}
			),
		):
			self.assertEqual("instruction", endpoints.endpoint("writer").model)
			self.assertEqual("specialized", endpoints.endpoint("planner").model)

	def test_missing_or_invalid_endpoint_is_not_reported_as_ready(self):
		with patch.object(
			frappe, "conf", frappe._dict({"joymedia_vision": {"base_url": "http://vision/v1"}})
		):
			self.assertFalse(endpoints.is_configured("vision"))
			with self.assertRaises(frappe.ValidationError):
				endpoints.endpoint("vision")

	def test_the_translator_has_its_own_model_or_uses_the_planner(self):
		planner = {"joymedia_planner": {"base_url": "http://llm/v1", "model": "tvc-lora"}}
		with patch.object(frappe, "conf", frappe._dict(planner)):
			self.assertEqual("tvc-lora", endpoints.endpoint("translator").model)
		with patch.object(
			frappe,
			"conf",
			frappe._dict(planner, joymedia_translator={"base_url": "http://llm/v1", "model": "base"}),
		):
			self.assertEqual(
				("base", 300.0),
				(endpoints.endpoint("translator").model, endpoints.endpoint("translator").timeout),
			)

	def test_structured_response_uses_standard_schema_by_default(self):
		schema = {"type": "object"}
		payload = endpoints.structured_response({}, schema, "evidence")
		self.assertEqual(payload["response_format"]["json_schema"]["schema"], schema)
		self.assertNotIn("structured_outputs", payload)

	def test_compact_runtime_transport_keeps_the_schema_without_duplicate_constraints(self):
		schema = {"type": "object"}
		payload = endpoints.structured_response(
			{"structured_output": {"transport": "structured_outputs", "compact": True}}, schema, "evidence"
		)
		self.assertEqual(payload, {"structured_outputs": {"json": schema, "disable_any_whitespace": True}})
		self.assertNotIn("response_format", payload)

	def test_invalid_structured_output_profiles_fail_before_network_io(self):
		for profile in [
			[],
			"invalid",
			{"transport": "unknown"},
			{"transport": "structured_outputs", "compact": "yes"},
		]:
			with self.subTest(profile=profile), self.assertRaises(ValueError):
				endpoints.structured_response({"structured_output": profile}, {}, "evidence")
