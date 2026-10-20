#!/usr/bin/env python3
"""Optional BiRefNet driver; writes alpha only and a source/model provenance record.

Run in a GPU environment with a separately cloned, pinned official BiRefNet repo.
No dependency on this model is introduced into the application. Review the matte
before selecting its PNG as source artwork; pale product edges can be missed.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--repository", type=Path, required=True)
	parser.add_argument("--model", default="ZhengPeng7/BiRefNet")
	parser.add_argument("--revision", required=True)
	parser.add_argument("--cache", type=Path, required=True)
	parser.add_argument("source", type=Path)
	parser.add_argument("output", type=Path)
	args = parser.parse_args()
	sys.path.insert(0, str(args.repository.resolve()))
	import torch
	from models.birefnet import BiRefNet
	from PIL import Image, ImageOps
	from torchvision import transforms

	model = BiRefNet.from_pretrained(args.model, revision=args.revision, cache_dir=str(args.cache), bb_pretrained=False)
	model = model.eval().to("cuda").half()
	transform = transforms.Compose([transforms.Resize((1024, 1024)), transforms.ToTensor(),
		transforms.Normalize([.485, .456, .406], [.229, .224, .225])])
	with Image.open(args.source) as source:
		image = ImageOps.exif_transpose(source).convert("RGB")
	with torch.inference_mode():
		mask = model(transform(image).unsqueeze(0).to("cuda").half())[-1].sigmoid().cpu()[0].squeeze()
	alpha = transforms.ToPILImage()(mask).resize(image.size, Image.Resampling.LANCZOS)
	result = image.convert("RGBA")
	result.putalpha(alpha)
	if result.convert("RGB").tobytes() != image.tobytes():
		raise ValueError("Matting changed source RGB pixels")
	result.save(args.output, "PNG")
	pin = subprocess.check_output(["git", "-C", str(args.repository), "rev-parse", "HEAD"], text=True).strip()
	args.output.with_suffix(".provenance.json").write_text(json.dumps({"source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
		"rgba_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(), "repository_commit": pin,
		"model": args.model, "revision": args.revision, "source_rgb_unchanged": True}, indent=2))


if __name__ == "__main__":
	main()
