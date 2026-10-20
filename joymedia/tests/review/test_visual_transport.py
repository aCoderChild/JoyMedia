from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from joymedia.services.review.consistency import _post_visual_request


class TestVisualTransport(TestCase):
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
		):
			report = run_temporal_check(check, frappe._dict(base_url="endpoint", model="vision", timeout=120))
		self.assertEqual(2, post.call_count)
		self.assertEqual(post.call_args_list[0], post.call_args_list[1])
		delay.assert_called_once_with(5)
		self.assertEqual("supported", report["results"][0]["verdict"])
