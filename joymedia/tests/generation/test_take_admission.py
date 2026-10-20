"""Concurrent admission decisions must precede all mutable render bookkeeping."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from joymedia.services.generation import takes


class TestTakeAdmission(TestCase):
	def test_remote_preflight_precedes_allocation_of_global_run_number(self):
		from unittest.mock import Mock

		import frappe

		events = []
		project = frappe._dict(name="P", workflow="W", storyboard_approval_status="Approved", approved_plan_signature="sig")
		project.follow_active_pipeline = Mock()
		project.reload = Mock()
		project.db_set = Mock()
		run = Mock(name="run")
		run.name = "R"
		run.insert.side_effect = lambda **kw: events.append("insert")
		with patch.object(takes.frappe, "get_doc", return_value=run), patch.object(takes.frappe.db, "commit"), \
			patch("joymedia.services.planning.signature.compute_plan_signature", return_value="sig"), \
			patch("joymedia.services.planning.signature.assert_plan_matches_approval"), \
			patch("joymedia.services.project.context.build_project_snapshot", return_value=(json.dumps({"generation_pipeline": "PIPE"}), "hash")), \
			patch.object(takes, "_continuation_source_task", return_value=None), \
			patch("joymedia.services.generation.orchestrator.validate_run_preflight", side_effect=lambda *args: events.append("preflight")), \
			patch("joymedia.services.generation.orchestrator.start_run_internal", return_value={"status": "Queued"}) as start:
			takes._start_takes_run_locked(project, ["S"])
		self.assertEqual(events, ["preflight", "insert"])
		start.assert_called_once_with("R", preflight_checked=True)

	def exercise(self, names):
		gate = threading.Lock()
		active, started = set(), []
		project = SimpleNamespace(name="PROJECT", reload=MagicMock())
		fake = SimpleNamespace(
			db=SimpleNamespace(commit=MagicMock()), local=SimpleNamespace(site="isolated-test"),
			cache=SimpleNamespace(lock=MagicMock(return_value=gate)),
			get_doc=lambda doctype, name: SimpleNamespace(name=name),
		)

		def check(project, shot):
			if shot.name in active:
				raise ValueError("scene busy")

		def start(project, shot_names, **kwargs):
			active.update(shot_names)
			started.extend(shot_names)
			return {"run": "RUN-" + shot_names[0]}

		with patch.object(takes, "frappe", fake), patch.object(takes, "_ensure_scene_free", side_effect=check), patch.object(
			takes, "_start_takes_run_locked", side_effect=start
		), ThreadPoolExecutor(max_workers=2) as pool:
			futures = [pool.submit(takes._start_takes_run, project, [name]) for name in names]
			results = []
			for future in futures:
				try:
					results.append(future.result())
				except ValueError as exc:
					results.append(str(exc))
		self.assertFalse(gate.locked())
		return results, started

	def test_two_tabs_cannot_queue_the_same_scene_twice(self):
		results, started = self.exercise(["SCENE-A", "SCENE-A"])
		self.assertEqual(["SCENE-A"], started)
		self.assertEqual(1, results.count("scene busy"))

	def test_independent_scenes_can_both_queue_through_the_project_gate(self):
		results, started = self.exercise(["SCENE-A", "SCENE-B"])
		self.assertEqual({"SCENE-A", "SCENE-B"}, set(started))
		self.assertTrue(all(isinstance(result, dict) for result in results))
