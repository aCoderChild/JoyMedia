import unittest

from joymedia.services.audio.speech import spoken_text


class TestSpokenText(unittest.TestCase):
	def test_silent_cue_does_not_become_narration(self):
		for text in ("Không thoại.", "No dialogue", "x", "", None):
			self.assertEqual("", spoken_text(text))

	def test_stage_directions_are_not_read_aloud(self):
		self.assertEqual("Ối!", spoken_text("Gấu kêu “Ối!”."))
		self.assertEqual("Đừng lo, có Shera đây!", spoken_text("VO nữ: “Đừng lo, có Shera đây!”"))
		self.assertEqual("Shera bốn lớp dày dặn.", spoken_text("VO: Shera bốn lớp dày dặn."))
