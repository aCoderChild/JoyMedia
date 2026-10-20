#!/usr/bin/env python3
"""Fail fast when a checkout no longer has the Frappe app package layout."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
	"pyproject.toml",
	"joymedia/__init__.py",
	"joymedia/hooks.py",
	"joymedia/modules.txt",
	"joymedia/joymedia/__init__.py",
	"joymedia/joymedia/doctype/__init__.py",
	"joymedia/frontend/package.json",
)


def main():
	missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
	if missing:
		print("Invalid JoyMedia application layout. Missing:", file=sys.stderr)
		for path in missing:
			print(f"  - {path}", file=sys.stderr)
		return 1
	print("JoyMedia Frappe application layout is valid.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
