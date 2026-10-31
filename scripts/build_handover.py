#!/usr/bin/env python3
"""Build a source and selected-demo handover ZIP from an explicit allowlist, never a Bench backup."""

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("joymedia/", "deploy/", "scripts/", "docs/handover/", "docs/licenses/", "database/")
ROOT_FILES = {
	"README.md",
	"pyproject.toml",
	"license.txt",
	".gitignore",
	".editorconfig",
	".eslintrc",
	".pre-commit-config.yaml",
	"docs/architecture.md",
	"docs/code-architecture.md",
	"docs/account-roles.md",
	"docs/production-pipeline.md",
	"docs/operations.md",
	".github/workflows/ci.yml",
	".github/workflows/linter.yml",
}
EXCLUDED_PARTS = {
	".git",
	"node_modules",
	"__pycache__",
	".cache",
	".ruff_cache",
	".pytest_cache",
	"env",
	".venv",
	"venv",
	"sites",
	"logs",
	"test-results",
	"playwright-report",
	"dist",
	"upstream",
	"verification",
	"research",
	"build",
	"out",
	"coverage",
	"htmlcov",
	".mypy_cache",
	".hypothesis",
	".tox",
	".nox",
	".vite",
	".parcel-cache",
	".turbo",
	".npm",
	".next",
	".nuxt",
	".output",
	".svelte-kit",
	".sass-cache",
	"__macosx",
	".ipynb_checkpoints",
	".vscode",
	".idea",
	".history",
	"tmp",
	"temp",
	"handover-dist",
}
EXCLUDED_NAMES = {
	".ds_store",
	"thumbs.db",
	"desktop.ini",
	".eslintcache",
	".stylelintcache",
	".coverage",
	"coverage.xml",
	"junit.xml",
	"test-results.xml",
	".python_history",
	".bash_history",
	".zsh_history",
	".npmrc",
	".pypirc",
	"site_config.json",
	"common_site_config.json",
}
GENERATED = ("joymedia/public/frontend/", "joymedia/templates/pages/_joymedia.html")
SECRET_PATTERNS = {
	"private key": re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
	"access token": re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16})"),
	"URL credentials": re.compile(rb"(?:https?|mysql|redis)://[^\s/@:]+:[^\s/@]+@"),
}
# Reviewed literal in the test that rejects URLs containing credentials. Keep
# this exception scoped to the exact bytes and path, never exempt a whole test.
TEST_LITERALS = {
	"joymedia/tests/workflows/test_comfyui.py": (b"http://user:" + b"password@server:8188",),
}


def allowed(path):
	p = Path(path)
	if p.is_absolute() or ".." in p.parts or "\\" in path:
		return False
	if any(part.lower() in EXCLUDED_PARTS for part in p.parts):
		return False
	if any(part.endswith((".egg-info", ".dist-info")) for part in p.parts):
		return False
	if p.name.lower() in EXCLUDED_NAMES or p.name.startswith(("._", ".coverage.")):
		return False
	if p.name.endswith("~"):
		return False
	if p.name.startswith(".env") and p.name != ".env.example":
		return False
	if p.suffix.lower() in {
		".pyc",
		".pyo",
		".log",
		".pem",
		".key",
		".zip",
		".bak",
		".gz",
		".env",
		".p12",
		".pfx",
		".db",
		".sqlite",
		".sqlite3",
		".whl",
		".map",
		".tsbuildinfo",
		".tmp",
		".temp",
		".swp",
		".swo",
		".orig",
		".rej",
		".prof",
		".o",
		".a",
		".so",
		".dylib",
		".dll",
		".exe",
		".class",
	}:
		return False
	if p.suffix == ".sql" and path != "database/sample.sql":
		return False
	if p.name.endswith(".local.json") or path.startswith(GENERATED):
		return False
	return path in ROOT_FILES or path.startswith(PREFIXES)


def source_files():
	if (ROOT / ".git").exists():
		# Current worktree bytes, including new handover files; never export history.
		paths = (
			subprocess.check_output(
				["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
			)
			.decode()
			.split("\0")
		)
	else:
		# Rebuilding an unpacked release needs no Git metadata.
		# Prune dependencies/caches before traversal, even after npm/build/test.
		paths = []
		for directory, dirs, names in os.walk(ROOT, followlinks=False):
			dirs[:] = [
				name
				for name in dirs
				if name.lower() not in EXCLUDED_PARTS and not name.endswith((".egg-info", ".dist-info"))
			]
			paths.extend(str((Path(directory) / name).relative_to(ROOT)) for name in names)
	result = {}
	for name in sorted(set(filter(None, paths))):
		if not allowed(name):
			continue
		p = ROOT / name
		if p.is_symlink() or any(parent.is_symlink() for parent in p.parents if parent != ROOT):
			raise ValueError(f"Refusing symlink: {name}")
		if not p.is_file():
			raise ValueError(f"Missing source file: {name}")
		result[name] = p.read_bytes()
	return result


def configured_secrets():
	"""Compare exact local secret values without copying or printing them."""
	secrets = set()

	def visit(value, key=""):
		if isinstance(value, dict):
			for k, v in value.items():
				visit(v, k)
		elif isinstance(value, list):
			for v in value:
				visit(v, key)
		elif (
			isinstance(value, str)
			and len(value) >= 8
			and re.search(r"password|secret|token|api_key|encryption_key", key, re.I)
		):
			secrets.add(value.encode())

	for p in [ROOT / "sites/common_site_config.json", *ROOT.glob("sites/*/site_config.json")]:
		if p.is_file():
			visit(json.loads(p.read_text()))
	return secrets


def check(files):
	secrets = configured_secrets()
	for name, data in files.items():
		scan_data = data
		for literal in TEST_LITERALS.get(name, ()):
			scan_data = scan_data.replace(literal, b"<reviewed-test-literal>")
		for label, pattern in SECRET_PATTERNS.items():
			if pattern.search(scan_data):
				raise ValueError(f"Potential {label} in {name}; review before packaging")
		if any(value in data for value in secrets):
			raise ValueError(f"Local configured secret found in {name}")
		if name.endswith(".py"):
			ast.parse(data, filename=name)
		if name.endswith(".json"):
			json.loads(data)
	for required in (
		"pyproject.toml",
		"joymedia/hooks.py",
		"joymedia/frontend/package-lock.json",
		"joymedia/demo/records.json",
		"joymedia/demo/manifest.json",
		"database/sample.sql",
		"README.md",
	):
		if required not in files:
			raise ValueError(f"Missing required handover file: {required}")
	manifest = json.loads(files["joymedia/demo/manifest.json"])
	expected_media = {"joymedia/demo/" + item["path"] for item in manifest["media"]}
	actual_media = {path for path in files if path.startswith("joymedia/demo/media/")}
	if expected_media != actual_media:
		raise ValueError("Demo media directory differs from its manifest")
	for item in manifest["media"]:
		path = "joymedia/demo/" + item["path"]
		if path not in files or hashlib.sha256(files[path]).hexdigest() != item["sha256"]:
			raise ValueError(f"Missing or changed demo media: {path}")
		if len(files[path]) != item["bytes"]:
			raise ValueError(f"Wrong media size: {path}")
	return len(secrets)


def sql_literal(value):
	if value is None:
		return "NULL"
	if isinstance(value, (int, float)):
		return str(value)
	if value == "":
		return "''"
	# UTF-8 hex avoids SQL-mode-dependent escaping and is accepted by MariaDB.
	return "CONVERT(0x" + str(value).encode().hex() + " USING utf8mb4)"


def sample_sql():
	def flatten(rows, parent=None, parentfield=None):
		for row in rows:
			values = {k: v for k, v in row.items() if not isinstance(v, list)}
			if parent:
				values.update(parent=parent["name"], parenttype=parent["doctype"], parentfield=parentfield)
			yield values
			for key, children in row.items():
				if isinstance(children, list):
					yield from flatten(children, row, key)

	rows = json.loads((ROOT / "joymedia/demo/records.json").read_text())
	lines = [
		"-- Selected Shera 14/33 and Auntie 5 snapshot. No users, credentials or jobs.",
		"-- Install joymedia and migrate FIRST. Import only once into an empty demo site.",
		"-- Preferred restore (DB + media): bench --site <site> execute joymedia.demo.seed.load",
		"-- After SQL import, run the same loader to copy and verify the bundled media.",
		"-- No DROP/DELETE/REPLACE. Schema is supplied by Frappe + JoyMedia DocTypes.",
		"SET NAMES utf8mb4;",
		"START TRANSACTION;",
	]
	allowed = {
		"Media Project",
		"Project Reference",
		"Shot",
		"Shot Reference",
		"Timeline Clip",
		"Media Asset",
		"Asset Version",
		"File",
		"Generation Workflow",
		"Workflow Binding",
		"Generation Pipeline",
		"Generation Pipeline Step",
	}
	for row in flatten(rows):
		doctype = row["doctype"]
		if doctype not in allowed:
			raise ValueError("Unexpected demo DocType")
		values = {k: v for k, v in row.items() if k != "doctype"}
		if any(not re.fullmatch(r"[a-z_]+", key) for key in values):
			raise ValueError("Invalid SQL column")
		columns = ", ".join(f"`{key}`" for key in values)
		literals = ", ".join(sql_literal(value) for value in values.values())
		lines.append(f"INSERT INTO `tab{doctype}` ({columns}) VALUES ({literals});")
	lines.append("COMMIT;")
	return ("\n".join(lines) + "\n").encode()


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--output", type=Path, default=ROOT / "handover-dist")
	parser.add_argument("--date", default=datetime.now(UTC).strftime("%Y%m%d"))
	parser.add_argument("--refresh-sql", action="store_true")
	args = parser.parse_args()
	if not re.fullmatch(r"\d{8}", args.date):
		parser.error("--date must be YYYYMMDD")
	stamp = datetime.strptime(args.date, "%Y%m%d")
	sql = sample_sql()
	if args.refresh_sql:
		(ROOT / "database/sample.sql").write_bytes(sql)
	if not (ROOT / "database/sample.sql").is_file() or (ROOT / "database/sample.sql").read_bytes() != sql:
		raise ValueError("sample.sql is stale; run again with --refresh-sql")
	files = source_files()
	secret_count = check(files)
	version = re.search(r'__version__\s*=\s*"([0-9.]+)"', (ROOT / "joymedia/__init__.py").read_text())[1]
	revision = (
		subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
		if (ROOT / ".git").exists()
		else "unpacked-source"
	)
	name = f"joymedia-v{version}-handover-{args.date}"
	manifest = {
		"package": name,
		"base_commit": revision,
		"source": "current working tree; see file hashes",
		"excluded": "Bench runtime, Git history, secrets, generated frontend, logs, research, private reports",
		"security_checks": {"known_local_secrets_compared": secret_count, "pattern_scan": "passed"},
		"files": {
			path: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
			for path, data in sorted(files.items())
		},
	}
	files["MANIFEST.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
	files["SHA256SUMS"] = "".join(
		f"{hashlib.sha256(data).hexdigest()}  {path}\n" for path, data in sorted(files.items())
	).encode()
	args.output.mkdir(parents=True, exist_ok=True)
	archive = args.output / f"{name}.zip"
	with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
		for path, data in sorted(files.items()):
			info = zipfile.ZipInfo(f"{name}/{path}", date_time=(*stamp.timetuple()[:3], 0, 0, 0))
			info.compress_type = zipfile.ZIP_DEFLATED
			info.external_attr = (0o100755 if path.endswith(".sh") else 0o100644) << 16
			z.writestr(info, data)
	with zipfile.ZipFile(archive) as z:
		expected = {f"{name}/{path}" for path in files}
		if len(z.namelist()) != len(expected) or set(z.namelist()) != expected:
			raise ValueError("ZIP file inventory differs from the approved file set")
		for entry in z.infolist():
			path = entry.filename.removeprefix(f"{name}/")
			if path not in {"MANIFEST.json", "SHA256SUMS"} and not allowed(path):
				raise ValueError(f"Excluded/generated file found in ZIP: {path}")
		if z.testzip():
			raise ValueError("ZIP CRC verification failed")
	digest = hashlib.sha256(archive.read_bytes()).hexdigest()
	archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
	print(f"Created {archive} ({archive.stat().st_size:,} bytes, {len(files)} files)")
	print(f"SHA256 {digest}")
	return 0


if __name__ == "__main__":
	try:
		sys.exit(main())
	except (ValueError, OSError) as exc:
		print(str(exc), file=sys.stderr)
		sys.exit(1)
