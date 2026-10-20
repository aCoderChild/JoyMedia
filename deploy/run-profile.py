#!/usr/bin/env python3
"""Start or health-check one GPU runtime profile without shell interpretation.

Profiles are data in ``/etc/joymedia/runtime.json``.  Keeping argv as a JSON
array avoids fragile shell quoting and lets an operator replace a model, server,
or ComfyUI command without editing a systemd unit or application code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_CONFIG = Path("/etc/joymedia/runtime.json")


def load_profiles(path: Path) -> dict:
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError) as exc:
		raise SystemExit(f"Cannot read runtime profile file {path}: {exc}") from exc
	profiles = data.get("profiles") if isinstance(data, dict) else None
	if not isinstance(profiles, dict):
		raise SystemExit(f"{path} must contain an object named 'profiles'.")
	return profiles


def profile(profiles: dict, name: str) -> dict:
	value = profiles.get(name)
	if not isinstance(value, dict):
		raise SystemExit(f"Runtime profile '{name}' is not configured.")
	argv = value.get("argv")
	if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
		raise SystemExit(f"Runtime profile '{name}' must define a non-empty string argv array.")
	if value.get("environment") is not None and not isinstance(value["environment"], dict):
		raise SystemExit(f"Runtime profile '{name}' environment must be an object.")
	return value


def wait_for(url: str, timeout: int) -> None:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		try:
			with urllib.request.urlopen(url, timeout=5) as response:
				if 200 <= response.status < 300:
					return
		except (OSError, urllib.error.URLError):
			pass
		time.sleep(1)
	raise SystemExit(f"Timed out after {timeout}s waiting for {url}")


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("profile", nargs="?")
	parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
	parser.add_argument("--wait", action="append", default=[], metavar="PROFILE")
	parser.add_argument("--timeout", type=int, default=180)
	parser.add_argument("--validate", action="store_true")
	args = parser.parse_args()
	profiles = load_profiles(args.config)
	for name in args.wait:
		value = profile(profiles, name)
		health_url = value.get("health_url")
		if not isinstance(health_url, str) or not health_url:
			raise SystemExit(f"Runtime profile '{name}' must define health_url before it can be waited on.")
		wait_for(health_url, args.timeout)
	if args.validate:
		if args.profile:
			profile(profiles, args.profile)
		elif not args.wait:
			for name in profiles:
				profile(profiles, name)
		return
	if not args.profile:
		parser.error("profile is required unless --validate is used")
	value = profile(profiles, args.profile)
	environment = os.environ.copy()
	environment.update({str(key): str(item) for key, item in (value.get("environment") or {}).items()})
	working_directory = value.get("working_directory")
	if working_directory:
		os.chdir(working_directory)
	os.execvpe(value["argv"][0], value["argv"], environment)


if __name__ == "__main__":
	main()
