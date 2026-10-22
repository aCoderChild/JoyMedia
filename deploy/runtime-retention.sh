#!/usr/bin/env bash
# Remove ComfyUI per-attempt copies that JoyMedia has already ingested, so the
# GPU host's shared storage allowance is not consumed by transient media.
# Kept: hand-placed inputs, output subfolders (places, references, music) and
# anything newer than the retention window. JoyMedia uploads fresh copies for
# every attempt and stores its results in Frappe, so old copies are never reused.
set -euo pipefail

root="${JOYMEDIA_RUNTIME_ROOT:-/var/lib/kubelet/joymedia-model-store/runtime}"
days="${JOYMEDIA_RETENTION_DAYS:-2}"
[ -d "$root/input" ] && [ -d "$root/output" ] || { echo "No ComfyUI runtime at $root" >&2; exit 1; }

freed=$(
	{
		find "$root/input" -maxdepth 1 -type f -name 'joymedia_*' -mtime "+$days" -printf '%s\n' -delete
		find "$root/output" -maxdepth 1 -type f -name 'TASK-*_ATT-*' -mtime "+$days" -printf '%s\n' -delete
		find "$root/scratch" -mindepth 1 -maxdepth 1 -mtime +1 -printf '%s\n' -exec rm -rf {} +
	} | awk '{s += $1} END {printf "%.2f", s / 1e9}'
)
echo "$(date -Is) removed ${freed} GB of per-attempt media older than ${days} days; free: $(df -h --output=avail / | tail -1 | tr -d ' ')"
