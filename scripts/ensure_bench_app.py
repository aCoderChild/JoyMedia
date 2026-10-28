"""Keep Bench's app list valid across Frappe versions."""

import sys
from pathlib import Path


def ensure_app(path: Path, app: str) -> None:
	if not app or any(char.isspace() for char in app):
		raise ValueError("App name must be a single non-empty name")
	apps = [line.strip() for line in path.read_text().splitlines() if line.strip()]
	if app not in apps:
		apps.append(app)
	path.write_text("\n".join(apps) + "\n")


if __name__ == "__main__":
	if len(sys.argv) != 3:
		raise SystemExit("Usage: ensure_bench_app.py APPS_FILE APP_NAME")
	ensure_app(Path(sys.argv[1]), sys.argv[2])
