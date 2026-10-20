#!/usr/bin/env python3
"""Run every test module of the app, one `bench run-tests --module` per module.

`bench run-tests --app joymedia` only finds the doctype-side tests and skips joymedia/tests, so CI and developers use
this instead. Run it from a Bench:

    python apps/joymedia/scripts/run_tests.py <site>            # everything
    python apps/joymedia/scripts/run_tests.py <site> planning   # only joymedia/tests/planning

Exit status is non-zero if any module fails; each failing module's output is printed.
"""

import datetime
import json
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "joymedia"


def test_modules(selection=None):
	modules = []
	for path in sorted(APP.rglob("test_*.py")):
		relative = path.relative_to(APP.parent).with_suffix("")
		if any(part in ("node_modules", "frontend") for part in relative.parts):
			continue
		if "def test_" not in path.read_text(encoding="utf-8"):
			continue  # a scaffold stub with no tests
		dotted = ".".join(relative.parts)
		if selection and selection not in dotted:
			continue
		modules.append(dotted)
	return modules


def main(argv):
	if not argv:
		print(__doc__)
		return 2
	site, selection = argv[0], (argv[1] if len(argv) > 1 else None)
	failed, total = [], 0
	report_dir = Path("/tmp") / (
		"joymedia-tests-" + datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%f")
	)
	report_dir.mkdir()
	results = []
	print(f"Full per-module logs: {report_dir}", flush=True)
	for module in test_modules(selection):
		result = subprocess.run(
			["bench", "--site", site, "run-tests", "--module", module],
			capture_output=True,
			text=True,
			stdin=subprocess.DEVNULL,
		)
		output = result.stdout + result.stderr
		log = report_dir / f"{module}.log"
		log.write_text(output, encoding="utf-8")
		ran = next((line for line in output.splitlines() if line.startswith("Ran ")), "no tests ran")
		ok = (
			result.returncode == 0
			and "FAILED" not in output
			and "TestRunnerError" not in output
			and ran != "no tests ran"
		)
		total += int(ran.split()[1]) if ran.startswith("Ran ") else 0
		results.append({"module": module, "ok": ok, "result": ran, "log": str(log)})
		print(("ok    " if ok else "FAIL  ") + module + "  " + ran, flush=True)
		if not ok:
			failed.append(module)
			# Print the traceback before the routine successful-case list. Keep
			# the complete log as evidence, including failures early in long modules.
			start = output.find("======================================================================")
			print(output[start : start + 3500] if start >= 0 else output[:3500], flush=True)
	print(f"\n{total} tests, {len(failed)} failing module(s)")
	(report_dir / "summary.json").write_text(
		json.dumps({"tests_run": total, "failed_modules": failed, "modules": results}, indent=2)
	)
	return 1 if failed else 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
