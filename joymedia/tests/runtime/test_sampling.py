from unittest import TestCase
from unittest.mock import patch

from joymedia.services.runtime.sampling import sampling


class TestSamplingProfiles(TestCase):
	def test_profiles_are_loaded_from_json_and_copied_for_each_request(self):
		first = sampling("vision_observation")
		original = dict(first)
		first["max_tokens"] = -1
		self.assertEqual(original, sampling("vision_observation"))

	def test_invalid_configuration_never_silently_chooses_a_default(self):
		for value in [
			{"temperature": True, "max_tokens": 100},
			{"temperature": 0, "max_tokens": 0},
			{"temperature": 0, "max_tokens": 100, "product": "hidden"},
		]:
			with (
				patch("joymedia.services.runtime.sampling._profiles", return_value={"operation": value}),
				self.assertRaises(ValueError),
			):
				sampling("operation")
