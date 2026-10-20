import hashlib
import tempfile
from pathlib import Path

from frappe.tests.utils import FrappeTestCase
from PIL import Image

from joymedia.services.keyframes.reference_board import compose_reference_board


class TestReferenceCompositor(FrappeTestCase):
	def test_transparency_and_reference_edges_are_preserved(self):
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "wide.png"
			image = Image.new("RGBA", (400, 100), (0, 0, 0, 0))
			image.paste((255, 0, 0, 255), (0, 0, 20, 100))
			image.paste((0, 0, 255, 255), (380, 0, 400, 100))
			image.save(path)
			board = compose_reference_board([{"path": str(path), "role": "Character"}], width=256, height=256)
			with Image.open(board["path"]) as result:
				self.assertEqual(result.getpixel((128, 128)), (255, 255, 255))
				self.assertGreater(result.getpixel((12, 128))[0], 220)
				self.assertGreater(result.getpixel((243, 128))[2], 220)
			self.assertIn("character reference", board["instruction"])

	def test_role_aware_board_is_reproducible(self):
		with tempfile.TemporaryDirectory() as directory:
			person = Path(directory) / "person.png"
			product = Path(directory) / "product.png"
			Image.new("RGB", (80, 100), (220, 40, 40)).save(person)
			Image.new("RGB", (120, 80), (40, 40, 220)).save(product)
			references = [
				{"path": str(person), "role": "People", "label": "Talent"},
				{"path": str(product), "role": "Product", "label": "Bottle"},
			]
			first = compose_reference_board(references, width=640, height=360)
			second = compose_reference_board(references, width=640, height=360)
			self.assertEqual(first["sha256"], second["sha256"])
			self.assertEqual(first["instruction"], second["instruction"])
			self.assertTrue(Path(first["path"]).exists())
			self.assertEqual(
				first["sha256"],
				hashlib.sha256(
					(
						"person:"
						+ hashlib.sha256(person.read_bytes()).hexdigest()
						+ "|product:"
						+ hashlib.sha256(product.read_bytes()).hexdigest()
						+ "|640x360|2x1|contain-white-v2"
					).encode("utf-8")
				).hexdigest(),
			)
			self.assertIn("person", first["instruction"])
			self.assertIn("product", first["instruction"])
