from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from joymedia.services.review.consistency import _post_visual_request


class TestVisualTransport(TestCase):
	def test_later_windows_are_not_starved_by_a_single_request_deadline(self):
		import json

		import frappe

		from joymedia.services.review.consistency import run_temporal_check
		from joymedia.services.scene.evidence import SequenceCheck

		claim = {"id": "action", "dimension": "action", "claim": "Lift the cup."}
		check = SequenceCheck(
			[b"before", b"after"],
			[{"index": 0, "time": 0}, {"index": 1, "time": 1}],
			[claim],
			{"asset_version": "V"},
		)
		response = Mock()
		response.json.return_value = {
			"choices": [
				{
					"message": {
						"content": json.dumps(
							{
								"observations": [
									{
										"id": "action",
										"verdict": "supported",
										"frames": [0, 1],
										"reason": "The cup moves from the table into the hand.",
									}
								],
							}
						)
					}
				}
			]
		}
		with (
			patch("joymedia.services.scene.evidence.batches", return_value=[((0, 1), [claim])] * 2),
			patch("joymedia.services.review.consistency.time.monotonic", side_effect=[0, 0, 0, 200, 200]),
			patch("joymedia.services.review.consistency._post_visual_request", return_value=response) as post,
			patch("joymedia.services.review.consistency._data_url", return_value="image"),
			patch("frappe.utils.file_manager.save_file", return_value=frappe._dict(file_url="report.json")),
			patch("frappe.db.get_value", return_value=None),
		):
			report = run_temporal_check(check, frappe._dict(base_url="endpoint", model="vision", timeout=120))
		self.assertEqual(2, post.call_count)
		self.assertEqual(240, report["judge"]["review_budget_seconds"])
		self.assertEqual("supported", report["results"][0]["verdict"])

	def test_dropped_observation_retries_the_same_request(self):
		response = Mock()
		payload = {"messages": ["same immutable image and question"]}
		with (
			patch(
				"joymedia.services.review.consistency.requests.post",
				side_effect=[requests.ConnectionError("dropped"), response],
			) as post,
			patch("joymedia.services.review.consistency.time.sleep"),
		):
			self.assertIs(response, _post_visual_request("endpoint", json=payload, timeout=(10, 120)))
		self.assertEqual(2, post.call_count)
		self.assertEqual(post.call_args_list[0], post.call_args_list[1])

	def test_unavailable_observation_still_fails_after_a_bounded_retry(self):
		with (
			patch(
				"joymedia.services.review.consistency.requests.post", side_effect=requests.Timeout("offline")
			) as post,
			patch("joymedia.services.review.consistency.time.sleep"),
			self.assertRaises(requests.Timeout),
		):
			_post_visual_request("endpoint")
		self.assertEqual(3, post.call_count)

	def test_an_http_result_is_not_rerolled(self):
		response = Mock(status_code=400)
		with patch("joymedia.services.review.consistency.requests.post", return_value=response) as post:
			self.assertIs(response, _post_visual_request("endpoint"))
		post.assert_called_once()

	def test_temporal_observations_use_the_same_transport_retry(self):
		import json

		import frappe

		from joymedia.services.review.consistency import run_temporal_check
		from joymedia.services.scene.evidence import SequenceCheck

		response = Mock()
		response.json.return_value = {
			"choices": [
				{
					"message": {
						"content": json.dumps(
							{
								"observations": [
									{
										"id": "action",
										"verdict": "supported",
										"frames": [0, 1],
										"reason": "The same cup is lifted.",
									}
								]
							}
						)
					}
				}
			]
		}
		check = SequenceCheck(
			[b"first", b"last"],
			[{"index": 0, "time": 0}, {"index": 1, "time": 1}],
			[{"id": "action", "dimension": "action", "claim": "Lift the cup."}],
			{"asset_version": "V"},
		)
		with (
			patch(
				"joymedia.services.review.consistency.requests.post",
				side_effect=[requests.ConnectionError("reconnecting"), response],
			) as post,
			patch("joymedia.services.review.consistency.time.sleep") as delay,
			patch("joymedia.services.review.consistency._data_url", return_value="image"),
			patch("frappe.utils.file_manager.save_file", return_value=frappe._dict(file_url="report.json")),
			patch("frappe.db.get_value", return_value=None),
		):
			report = run_temporal_check(check, frappe._dict(base_url="endpoint", model="vision", timeout=120))
		self.assertEqual(2, post.call_count)
		self.assertEqual(post.call_args_list[0], post.call_args_list[1])
		delay.assert_called_once_with(5)
		self.assertEqual("supported", report["results"][0]["verdict"])


class TestEvidenceReuse(TestCase):
	def test_identical_recheck_evidence_reuses_the_stored_file(self):
		import frappe

		from joymedia.services.review.consistency import run_temporal_check
		from joymedia.services.scene.evidence import SequenceCheck

		check = SequenceCheck(
			[], [], [], {"evidence_doctype": "Generation Artifact", "evidence_name": "GART"}
		)
		with (
			patch("joymedia.services.scene.evidence.batches", return_value=[]),
			patch("frappe.db.get_value", return_value="/private/files/existing.json"),
			patch("frappe.utils.file_manager.save_file") as save,
		):
			report = run_temporal_check(check, frappe._dict(base_url="endpoint", model="vision", timeout=120))
		save.assert_not_called()
		self.assertEqual("/private/files/existing.json", report["evidence_file"])
