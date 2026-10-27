#!/usr/bin/env bash
set -euo pipefail

# Add a second dedicated planner to a Bench development Procfile. Run from the
# bench root. Existing entries are left intact and rerunning this is safe.
procfile="${1:-Procfile}"
if [[ ! -f "$procfile" ]] || ! grep -q '^worker_planning:' "$procfile"; then
	echo "Expected a Bench Procfile with worker_planning: $procfile" >&2
	exit 1
fi
if ! grep -q '^worker_planning_2:' "$procfile"; then
	printf '%s\n' 'worker_planning_2: bench worker --queue joymedia_planning 1>> logs/worker_planning_2.log 2>> logs/worker_planning_2.error.log' >> "$procfile"
fi
