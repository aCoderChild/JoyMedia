#!/usr/bin/env python3
"""Prune stale, source-backed temporary uploads for one account (dry-run by default).

Only exact joymedia_<UUID> basenames from terminal, immutable Attempt graphs
qualify. Original source files must still exist locally. Live ComfyUI queue inputs
are protected again immediately before deletion. Application artifacts and model
weights are never deleted. Run from Bench; SSH is an explicit operator option.
"""

import argparse
import datetime
import json
import re
import shlex
import subprocess
from pathlib import Path

import frappe

PATTERN = re.compile(r"joymedia_[a-f0-9]{32}\.[A-Za-z0-9]{1,8}")


def uploaded_names(value):
	if isinstance(value, dict):
		return set().union(*(uploaded_names(v) for v in value.values())) if value else set()
	if isinstance(value, list):
		return set().union(*(uploaded_names(v) for v in value)) if value else set()
	return {value} if isinstance(value, str) and PATTERN.fullmatch(value) else set()


def candidates(owner, minimum_age_hours, endpoint):
	cutoff = frappe.utils.now_datetime() - datetime.timedelta(hours=minimum_age_hours)
	attempts = frappe.db.sql(
		"""select a.name, a.resolved_workflow_json, a.generation_task, t.workflow
		from `tabGeneration Attempt` a join `tabGeneration Task` t on t.name=a.generation_task
		join `tabGeneration Run` r on r.name=t.generation_run
		join `tabMedia Project` p on p.name=r.media_project
		where p.owner=%s and a.status in ('Completed','Failed','Cancelled') and a.creation<%s
		and (a.comfyui_endpoint_url=%s or ifnull(a.comfyui_endpoint_url,'')='')""",
		(owner, cutoff, endpoint),
		as_dict=True,
	)
	result, checked, contracts = set(), {}, {}
	for attempt in attempts:
		if attempt.generation_task not in checked:
			inputs = frappe.get_all(
				"Generation Input",
				filters={"parent": attempt.generation_task},
				fields=["asset_version", "generation_artifact"],
			)
			paths = []
			for row in inputs:
				if row.asset_version:
					url = frappe.db.get_value("Asset Version", row.asset_version, "file")
				elif row.generation_artifact:
					url = frappe.db.get_value("Generation Artifact", row.generation_artifact, "frappe_file")
				else:
					paths.append(False)
					continue
				file = frappe.db.get_value("File", {"file_url": url}, "name") if url else None
				paths.append(bool(file and Path(frappe.get_doc("File", file).get_full_path()).is_file()))
			checked[attempt.generation_task] = bool(paths) and all(paths)
		if checked[attempt.generation_task]:
			if attempt.workflow not in contracts:
				contracts[attempt.workflow] = frappe.get_all(
					"Workflow Binding",
					filters={"parent": attempt.workflow, "value_type": ["in", ["File Path", "File Paths"]]},
					fields=["node_key", "input_name"],
				)
			graph = json.loads(attempt.resolved_workflow_json or "{}")
			for binding in contracts[attempt.workflow]:
				result |= uploaded_names(
					(graph.get(binding.node_key) or {}).get("inputs", {}).get(binding.input_name)
				)
	return sorted(result)


REMOTE = r"""
import sys,json,re,time,urllib.request
from pathlib import Path
request=json.load(sys.stdin)
root=Path(request['directory']).resolve()
if not root.is_dir():raise ValueError('Input directory does not exist')
pattern=re.compile(r'joymedia_[a-f0-9]{32}\.[A-Za-z0-9]{1,8}')
def names(value):
 if isinstance(value,dict):return set().union(*(names(v) for v in value.values())) if value else set()
 if isinstance(value,list):return set().union(*(names(v) for v in value)) if value else set()
 return {value} if isinstance(value,str) and pattern.fullmatch(value) else set()
with urllib.request.urlopen(request['queue_url'],timeout=20) as response: protected=names(json.load(response))
rows=[];total=0
for name in request['names']:
 if not pattern.fullmatch(name):raise ValueError('Unsafe cache filename')
 if name in protected:continue
 path=root/name
 if path.is_symlink() or not path.is_file():continue
 stat=path.stat()
 if time.time()-stat.st_mtime < request['hours']*3600:continue
 if total+stat.st_size > request['max_bytes']:continue
 total+=stat.st_size
 rows.append({'name':name,'bytes':stat.st_size,'mtime':stat.st_mtime})
if request['apply']:
 with urllib.request.urlopen(request['queue_url'],timeout=20) as response: protected=names(json.load(response))
 for row in rows:
  path=root/row['name']
  if row['name'] not in protected and path.is_file() and not path.is_symlink() and path.stat().st_mtime==row['mtime']:
   path.unlink();row['deleted']=True
print(json.dumps({'apply':request['apply'],'bytes':sum(r['bytes'] for r in rows),'files':rows},indent=2))
"""


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("site")
	parser.add_argument("owner")
	parser.add_argument("--ssh-target", required=True)
	parser.add_argument("--ssh-port", type=int, default=22)
	parser.add_argument("--ssh-key", type=Path, required=True)
	parser.add_argument("--remote-input-directory", required=True)
	parser.add_argument("--remote-queue-url", default="http://127.0.0.1:8188/queue")
	parser.add_argument("--minimum-age-hours", type=float, default=24)
	parser.add_argument("--max-bytes", type=int, default=1024**3)
	parser.add_argument("--apply", action="store_true")
	args = parser.parse_args()
	if args.minimum_age_hours < 1 or not 0 < args.max_bytes <= 5 * 1024**3:
		raise ValueError("Use at least one hour retention and at most 5 GiB per operation")
	frappe.init(site=args.site, sites_path="sites")
	frappe.connect()
	try:
		names = candidates(
			args.owner, args.minimum_age_hours, frappe.conf.get("comfyui_base_url", "").rstrip("/")
		)
	finally:
		frappe.destroy()
	request = dict(
		names=names,
		directory=args.remote_input_directory,
		queue_url=args.remote_queue_url,
		hours=args.minimum_age_hours,
		max_bytes=args.max_bytes,
		apply=args.apply,
	)
	result = subprocess.run(
		[
			"ssh",
			"-i",
			str(args.ssh_key),
			"-p",
			str(args.ssh_port),
			"-o",
			"BatchMode=yes",
			args.ssh_target,
			"python3 -c " + shlex.quote(REMOTE),
		],
		input=json.dumps(request),
		capture_output=True,
		text=True,
		check=True,
		timeout=120,
	)
	print(result.stdout)


if __name__ == "__main__":
	main()
