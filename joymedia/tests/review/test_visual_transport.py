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
