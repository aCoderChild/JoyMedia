"""Every server method the studio calls must exist and be whitelisted.

Moving or renaming a module silently breaks the browser's calls (they are plain strings); this catches it.
"""

import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

FRONTEND = Path(frappe.get_app_path("joymedia")) / "frontend" / "src"
CALL = re.compile(r"""["'`](joymedia\.(?:api|services)(?:\.[a-z_0-9]+)+)["'`]""")


def called_methods():
	methods = set()
	for path in FRONTEND.rglob("*"):
		if path.suffix in (".vue", ".js"):
			methods.update(CALL.findall(path.read_text(encoding="utf-8")))
	return sorted(methods)


class TestFrontendApiContract(FrappeTestCase):
	def test_the_studio_calls_something(self):
		self.assertGreater(len(called_methods()), 20)

	def test_every_method_the_studio_calls_exists_and_is_whitelisted(self):
		problems = []
		for dotted in called_methods():
			try:
				function = frappe.get_attr(dotted)
			except (ImportError, AttributeError) as exc:
				problems.append(f"{dotted}: not found ({exc})")
				continue
			if function not in frappe.whitelisted:
				problems.append(f"{dotted}: exists but is not whitelisted")
		self.assertEqual([], problems)
