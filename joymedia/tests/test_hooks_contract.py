"""Every function that hooks.py names (scheduler jobs, document events, overrides) must exist."""

import frappe
from frappe.tests.utils import FrappeTestCase

from joymedia import hooks


def _dotted_paths(value):
	if isinstance(value, str):
		if value.startswith("joymedia.") and "." in value[len("joymedia.") :]:
			yield value
	elif isinstance(value, dict):
		for item in value.values():
			yield from _dotted_paths(item)
	elif isinstance(value, (list, tuple)):
		for item in value:
			yield from _dotted_paths(item)


class TestHooksContract(FrappeTestCase):
	def test_every_function_named_in_hooks_resolves(self):
		paths = set()
		for name in (
			"doc_events",
			"scheduler_events",
			"override_whitelisted_methods",
			"override_doctype_class",
			"on_session_creation",
		):
			paths.update(_dotted_paths(getattr(hooks, name, None)))
		self.assertGreaterEqual(len(paths), 4)
		missing = []
		for path in sorted(paths):
			try:
				frappe.get_attr(path)
			except (ImportError, AttributeError) as exc:
				missing.append(f"{path}: {exc}")
		self.assertEqual([], missing)
