import hashlib
import tempfile
from pathlib import Path

from PIL import Image
from frappe.tests.utils import FrappeTestCase

from joymedia.services.reference_compositor import compose_reference_board


class TestReferenceCompositor(FrappeTestCase):
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
				hashlib.sha256((
					"person:" + hashlib.sha256(person.read_bytes()).hexdigest()
					+ "|product:" + hashlib.sha256(product.read_bytes()).hexdigest()
					+ "|640x360|2x1"
				).encode("utf-8")).hexdigest(),
			)
			self.assertIn("person", first["instruction"])
			self.assertIn("product", first["instruction"])
