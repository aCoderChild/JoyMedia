#!/usr/bin/env python3
"""Review real immutable video assets from an external, owner-scoped case manifest.

Run in Bench with env/bin/python. This does not submit generation or select takes.
The configured vision capability is used; no benchmark checkpoints are loaded.
"""

import argparse
import json
import time
from pathlib import Path

import frappe


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("site")
	parser.add_argument("manifest", type=Path)
	args = parser.parse_args()
	manifest = json.loads(args.manifest.read_text())
	frappe.init(site=args.site, sites_path="sites")
	frappe.connect()
	try:
		frappe.set_user(manifest["account"])
		from joymedia.services.review.consistency import run_temporal_check, temporal_check

		results = []
		for index, case in enumerate(manifest["cases"]):
			shot = frappe.get_doc("Shot", case["shot"])
			frappe.get_doc("Media Project", shot.media_project)._require_read_access()
			asset = frappe.get_doc("Asset Version", case["asset_version"])
			project = frappe.db.get_value("Media Asset", asset.media_asset, "media_project")
			if not project:
				raise ValueError("Evaluation cases require a project-scoped video asset.")
			frappe.get_doc("Media Project", project)._require_read_access()
			# An in-memory candidate, never a take-selection or approval mutation.
			shot.selected_output_asset_version = asset.name
			started = time.monotonic()
			print(f"Reviewing case {index + 1}: {asset.name}", flush=True)
			report = run_temporal_check(temporal_check(shot, asset.file))
			frappe.db.commit()
			path = args.manifest.parent / f"case-{index + 1}-evidence.json"
			path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
			results.append(
				{
					"case": case,
					"status": report["status"],
					"report": str(path),
					"seconds": time.monotonic() - started,
				}
			)
			(args.manifest.parent / "evaluation-summary.json").write_text(json.dumps(results, indent=2))
			print(json.dumps(results[-1]), flush=True)
			if case.get("expected") and report["status"] != case["expected"]:
				raise AssertionError(
					f"Case {index + 1} expected {case['expected']}, got {report['status']}; evidence was preserved."
				)
	finally:
		frappe.destroy()


if __name__ == "__main__":
	main()
