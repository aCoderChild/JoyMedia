#!/usr/bin/env python3
"""Install pinned upstream reference preparation onto a separate large volume.

Requires an existing Torch/Transformers GPU environment. Does not change its
packages, restart ComfyUI, overwrite operator edits, or enable a site policy.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--storage-root", type=Path, required=True)
	parser.add_argument("--comfyui", type=Path, required=True)
	args = parser.parse_args()
	root = args.storage_root.resolve()
	root.mkdir(parents=True, exist_ok=True)
	if root.stat().st_dev == Path("/").stat().st_dev or shutil.disk_usage(root).free < 64 * 1024**3:
		raise SystemExit("Use a separate large mounted volume with at least 64 GiB free.")
	runtime = root / "runtime"
	cache = runtime / "cache/huggingface/hub"
	for name in ["scratch", "repositories", "adapters", "cache"]:
		(runtime / name).mkdir(parents=True, exist_ok=True)
	os.environ.update(
		TMPDIR=str(runtime / "scratch"),
		XDG_CACHE_HOME=str(runtime / "cache"),
		HF_HOME=str(cache.parent),
		HF_HUB_CACHE=str(cache),
	)
	lock = json.loads(Path(__file__).with_name("reference-retention.lock.json").read_text())
	pins = {}
	for repo in lock["repositories"]:
		target = runtime / "repositories" / repo["name"]
		if not target.exists():
			subprocess.run(["git", "clone", "--depth", "1", repo["url"], str(target)], check=True)
		if subprocess.check_output(["git", "-C", str(target), "status", "--porcelain"], text=True).strip():
			raise SystemExit("Refusing to overwrite modified upstream repository: " + str(target))
		subprocess.run(
			["git", "-C", str(target), "fetch", "--depth", "1", "origin", repo["commit"]], check=True
		)
		subprocess.run(["git", "-C", str(target), "checkout", "--detach", repo["commit"]], check=True)
		pins[repo["name"]] = repo["commit"]
	from huggingface_hub import snapshot_download

	config = dict(
		storage_root=str(root),
		repository=str(runtime / "repositories/BiRefNet"),
		cache=str(cache),
		repositories=pins,
	)
	for capability, model in lock["models"].items():
		snapshot_download(
			model["repository"],
			revision=model["revision"],
			cache_dir=str(cache),
			allow_patterns=["*.json", "*.safetensors", "vocab.txt", "tokenizer.model"],
		)
		config[capability + "_model"] = model["repository"]
		config[capability + "_revision"] = model["revision"]
	source = Path(__file__).with_name("comfy-reference-retention")
	target = runtime / "adapters/comfy-reference-retention"
	target.mkdir(parents=True, exist_ok=True)
	for name in ["__init__.py", "worker.py", "NOTICE", "GroundingDINO-LICENSE"]:
		shutil.copy2(source / name, target / name)
	config["adapter_sha256"] = hashlib.sha256(
		b"".join((target / n).read_bytes() for n in ["__init__.py", "worker.py"])
	).hexdigest()
	manifest = runtime / "reference-retention.json"
	manifest.write_text(json.dumps(config, sort_keys=True, indent=2))
	link = args.comfyui / "custom_nodes/joymedia-reference-retention"
	if link.exists() or link.is_symlink():
		if not link.is_symlink() or link.resolve() != target:
			raise SystemExit("A different reference adapter already occupies " + str(link))
	else:
		link.symlink_to(target)
	print(
		json.dumps(
			dict(
				manifest=str(manifest),
				recipe_sha256=hashlib.sha256(
					json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
				).hexdigest(),
			),
			indent=2,
		)
	)


if __name__ == "__main__":
	main()
