from unittest import TestCase

from joymedia.services.audio.direction import narration_delivery, score_direction, voiceover_writer_rules


class TestCommercialAudioDirection(TestCase):
	def test_score_keeps_the_authored_identity_and_adds_a_timed_arrangement(self):
		prompt = score_direction("bright acoustic guitar at 124 BPM", 30)
		self.assertIn("bright acoustic guitar at 124 BPM", prompt)
		self.assertIn("0-3.6s", prompt)
		self.assertIn("final resolve", prompt)
		self.assertIn("No vocals", prompt)

	def test_score_fills_missing_tempo_and_instrumentation_without_claiming_a_product_fact(self):
		prompt = score_direction("playful and warm", 20)
		self.assertIn("around 108 BPM", prompt)
		self.assertIn("hand percussion", prompt)
		self.assertNotIn("Shera", prompt)

	def test_voice_delivery_has_a_contour_without_changing_the_text(self):
		self.assertEqual("hook", narration_delivery(0, 3)["role"])
		self.assertEqual("+8%", narration_delivery(0, 3)["rate"])
		self.assertEqual("benefit", narration_delivery(1, 3)["role"])
		self.assertEqual("cta", narration_delivery(2, 3)["role"])
		self.assertIn("generic introduction", voiceover_writer_rules())
