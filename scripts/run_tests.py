#!/usr/bin/env python3
"""Run every test module of the app, one `bench run-tests --module` per module.

`bench run-tests --app joymedia` only finds the doctype-side tests and skips joymedia/tests, so CI and developers use
this instead. Run it from a Bench:

    python apps/joymedia/scripts/run_tests.py <site>            # everything
    python apps/joymedia/scripts/run_tests.py <site> planning   # only joymedia/tests/planning

Exit status is non-zero if any module fails; each failing module's output is printed.
"""

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
	for module in test_modules(selection):
		result = subprocess.run(
			["bench", "--site", site, "run-tests", "--module", module], capture_output=True, text=True, stdin=subprocess.DEVNULL
		)
		output = result.stdout + result.stderr
		ran = next((line for line in output.splitlines() if line.startswith("Ran ")), "no tests ran")
		ok = result.returncode == 0 and "FAILED" not in output and "TestRunnerError" not in output and ran != "no tests ran"
		total += int(ran.split()[1]) if ran.startswith("Ran ") else 0
		print(("ok    " if ok else "FAIL  ") + module + "  " + ran)
		if not ok:
			failed.append(module)
			print(output[-3000:])
	print(f"\n{total} tests, {len(failed)} failing module(s)")
	return 1 if failed else 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
