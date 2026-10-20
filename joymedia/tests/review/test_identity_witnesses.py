from unittest import TestCase

from joymedia.services.review.admission import _identity_witnesses


class TestIdentityWitnesses(TestCase):
	def counts(self, values):
		return [{"frame": i, "count": v} for i, v in enumerate(values)]

	def test_intermittent_actor_uses_three_interior_views(self):
		counts = self.counts([0, 0] + [1] * 10 + [0, 0, 0, 0])
		self.assertEqual([4, 7, 9], _identity_witnesses(counts))

	def test_persistent_actor_retains_endpoint_coverage(self):
		self.assertEqual([0, 4, 7], _identity_witnesses(self.counts([1] * 8)))

	def test_short_visibility_checks_every_available_view(self):
		self.assertEqual([1, 2, 3, 4], _identity_witnesses(self.counts([0, 1, 1, 1, 1, 0])))

	def test_no_actor_or_unknown_counts_are_not_identity_evidence(self):
		self.assertEqual([], _identity_witnesses(self.counts([0, None, 0])))
