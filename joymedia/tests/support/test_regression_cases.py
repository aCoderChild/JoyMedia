from frappe.tests.utils import FrappeTestCase

from joymedia.tests.support import regression_cases as cases


class TestCaseAssets(FrappeTestCase):
	def test_the_generated_cutouts_are_really_transparent_and_pasteable(self):
		for make in (cases._box_cutout, cases._logo_cutout):
			image = make()
			self.assertEqual("RGBA", image.mode)
			self.assertEqual(0, image.getchannel("A").getextrema()[0])
			self.assertEqual(255, image.getchannel("A").getextrema()[1])

	def test_every_case_declares_a_known_shape_and_expectations(self):
		for name, case in cases.CASES.items():
			self.assertIn(case["preset"], cases.SHAPES, name)
			self.assertIn("pasted", case["expect"], name)
			# Only transparent cutouts are pasted; an opaque photo guides the image model instead.
			self.assertLessEqual(len(case["expect"]["pasted"]), len(case["references"]), name)

	def test_a_missing_keyframe_fails_the_check(self):
		self.assertEqual(
			[("keyframe rendered", False, "no image")], cases.evaluate("text-only-portrait", None, "x")
		)
