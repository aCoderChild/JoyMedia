from frappe.tests.utils import FrappeTestCase

from joymedia.services.planning.roles import (
	family_role,
	names_family,
	role_look,
	role_name,
	role_size,
	role_words,
)


class TestFamilyRoles(FrappeTestCase):
	def test_roles_are_read_from_vietnamese_and_english_names(self):
		cases = {
			"Gấu mẹ (mother mascot)": "mother",
			"Mẹ Lan": "mother",
			"Gấu bố": "father",
			"Gấu ba": "father",
			"Ông nội": "grandfather",
			"Mascot ông": "grandfather",
			"Bà ngoại": "grandmother",
			"Grandma bear": "grandmother",
			"Chị gái Lan": "older_child",
			"Big brother bear": "older_child",
			"Gấu con (kid mascot)": "child",
			"Bé Mai": "child",
			"Bear cub": "child",
			"Baby panda": "child",
		}
		for label, role in cases.items():
			self.assertEqual(role, family_role(label), label)

	def test_words_that_only_look_like_roles_give_none(self):
		# "con" before a noun or after a number is a classifier; "ba" alone is "three".
		for label in (
			"Con gấu",
			"ba con gấu",
			"2 con gấu",
			"ba",
			"Contest winner",
			"Concept",
			"Gấu Shera mascot",
			"",
		):
			self.assertIsNone(family_role(label), label)

	def test_the_first_role_word_in_a_name_wins(self):
		self.assertEqual("child", family_role("Gấu con của mẹ"))
		self.assertEqual("mother", family_role("Mother of the cub"))

	def test_size_name_and_look_follow_the_role(self):
		self.assertEqual(
			(1.0, 0.55, 0.75, 1.0), tuple(role_size(n) for n in ("Gấu mẹ", "Gấu con", "Chị gái", "Gấu Shera"))
		)
		self.assertEqual("mother", role_name("Gấu mẹ"))
		self.assertIsNone(role_name("Gấu Shera"))
		self.assertTrue(
			role_look("Ông nội").startswith("with the build of a grandfather: an elderly full-grown adult")
		)
		self.assertTrue(role_look("Chị gái").startswith("with the build of an older child:"))
		self.assertIn("keeping exactly the reference subject's face, colours", role_look("Gấu con"))
		self.assertIn("no extra limbs or digits absent from the reference", role_look("Gấu con"))
		self.assertEqual("", role_look("Gấu Shera"))
		self.assertIn("cub", role_words("the kid mascot"))
		self.assertEqual((), role_words("character 1"))

	def test_words_for_the_whole_family(self):
		for text in ("Cả gia đình cười vui", "The whole family laughs", "bố mẹ ôm con", "Everyone claps"):
			self.assertTrue(names_family(text), text)
		for text in ("Gấu con làm đổ nước, sợ mẹ mắng", "Sản phẩm ở giữa", ""):
			self.assertFalse(names_family(text), text)
