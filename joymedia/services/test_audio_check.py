import subprocess
import tempfile
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from joymedia.services.audio_check import effects_score, is_effects_like


def _tone(path, source):
	subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", source, "-t", "2", "-c:a", "pcm_s16le", str(path)], check=True)


class TestEffectsScreen(FrappeTestCase):
	def test_noise_counts_as_effects_and_a_steady_tone_does_not(self):
		with tempfile.TemporaryDirectory() as folder:
			noise, tone, silence = (Path(folder) / name for name in ("noise.wav", "tone.wav", "silence.wav"))
			_tone(noise, "anoisesrc=color=white:amplitude=0.3:sample_rate=16000")
			_tone(tone, "sine=frequency=220:sample_rate=16000")
			_tone(silence, "anullsrc=r=16000:cl=mono")
			self.assertTrue(is_effects_like(noise))
			self.assertFalse(is_effects_like(tone))
			self.assertGreater(effects_score(noise), effects_score(tone))
			self.assertIsNone(is_effects_like(silence))
