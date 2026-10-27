"""Which failures are worth rendering again."""

from unittest import TestCase

from joymedia.services.generation.failures import classify_failure


class TestFailureClassification(TestCase):
	def test_an_interrupted_execution_is_not_a_workflow_defect(self):
		log = "[['execution_cached', {'nodes': ['6', '13']}], ['execution_interrupted', {'node_id': '14'}]]"
		self.assertEqual("Infrastructure", classify_failure(log, "Workflow"))

	def test_a_missing_node_is_still_a_workflow_defect(self):
		self.assertEqual("Workflow", classify_failure("Node type MiniMaxH3Foo not found"))
