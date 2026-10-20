#!/usr/bin/env python3
"""Move ComfyUI writable media directories onto a separate large volume.

Run while its queue is idle. Existing URLs keep working through symlinks. Model
downloads, repository checkouts and caches belong under the same storage root.
"""

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


def inventory(root):
	result = {}
	for path in sorted(root.rglob("*")):
		name = str(path.relative_to(root))
		if path.is_symlink():
			result[name] = {"link": os.readlink(path)}
		elif path.is_file():
			with path.open("rb") as stream:
				digest = hashlib.file_digest(stream, "sha256").hexdigest()
			result[name] = {"bytes": path.stat().st_size, "sha256": digest}
	return result


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--comfy-root", type=Path, required=True)
	parser.add_argument("--storage-root", type=Path, required=True)
	args = parser.parse_args()
	storage = args.storage_root.resolve()
	storage.mkdir(parents=True, exist_ok=True)
	if storage.stat().st_dev == Path("/").stat().st_dev:
		raise ValueError("GPU storage must be on a separate mounted volume, not the root disk.")
	if shutil.disk_usage(storage).free < 64 * 1024**3:
		raise ValueError("GPU storage needs at least 64 GiB free.")
	for category in ("downloads", "repositories", "cache", "scratch"):
		(storage / category).mkdir(exist_ok=True)
	results = []
	for name in ("input", "output", "temp"):
		source = args.comfy_root / name
		target = storage / name
		if source.is_symlink():
			if source.resolve() != target:
				raise ValueError(f"{source} points to a different location; inspect it before moving.")
			results.append({"directory": name, "status": "Already on storage volume"})
			continue
		before = inventory(source) if source.exists() else {}
		if target.exists():
			if inventory(target) != before:
				raise ValueError(f"{target} has different contents; no files were replaced.")
		else:
			if source.exists():
				shutil.copytree(source, target, symlinks=True)
			else:
				target.mkdir()
		if inventory(target) != before or (source.exists() and inventory(source) != before):
			raise ValueError(f"{name} changed during copying; originals retained.")
		backup = source.with_name(name + ".storage-migration-backup")
		if backup.exists():
			raise ValueError(f"{backup} already exists; inspect the previous migration.")
		if source.exists():
			source.rename(backup)
		try:
			source.symlink_to(target, target_is_directory=True)
		except Exception:
			if backup.exists():
				backup.rename(source)
			raise
		if backup.exists():
			shutil.rmtree(backup)  # verified identical bytes remain on the mounted volume
		results.append({"directory": name, "status": "Moved and SHA-256 verified", "files": len(before)})
	print(json.dumps({"storage_root": str(storage), "directories": results}))


if __name__ == "__main__":
	main()
