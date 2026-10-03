import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia.joymedia.doctype.project_reference.project_reference import assign_reference_key


class TestProjectReferenceKey(FrappeTestCase):
	def _key(self, label, existing=()):
		project = frappe._dict(selected_media=[frappe._dict(name=f"R{n}", reference_key=key) for n, key in enumerate(existing)])
		reference = frappe._dict(name="NEW", reference_key="", label=label, asset_version=None, reference_role="Environment")
		assign_reference_key(reference, project)
		return reference.reference_key

	def test_vietnamese_names_are_transliterated(self):
		self.assertEqual("toa_thap_riviera_point_luc_hoang_hon", self._key("tòa tháp Riviera Point lúc hoàng hôn"))
		self.assertEqual("san_dien_da_nang", self._key("Sân điền Đà Nẵng"))

	def test_keys_stay_unique(self):
		self.assertEqual("ho_boi_2", self._key("hồ bơi", existing=["ho_boi"]))
