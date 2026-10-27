#!/usr/bin/env bash
# Run on the GPU host as the dedicated Bench owner. The sole argument is a verified main commit.
set -Eeuo pipefail

die() { printf 'Deploy stopped: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || die 'provide one full Git commit SHA'
target_sha=$1
config_file=${JOYMEDIA_DEPLOY_CONFIG:-/etc/joymedia/deploy.env}
[[ -f "$config_file" ]] || die "missing server-side configuration: $config_file"
# This file must be owned by the server administrator. Never transmit credentials through CI logs.
# shellcheck source=/dev/null
source "$config_file"
: "${BENCH_DIR:?set BENCH_DIR in deploy.env}"
: "${SITE:?set SITE in deploy.env}"
: "${BACKUP_ROOT:?set BACKUP_ROOT in deploy.env}"
: "${HEALTH_URL:?set HEALTH_URL in deploy.env}"
[[ $SITE =~ ^[a-zA-Z0-9.-]+$ ]] || die 'invalid site name'
[[ $BENCH_DIR = /* ]] || die 'BENCH_DIR must be an absolute path'
[[ -d "$BENCH_DIR/sites/$SITE" && -x "$BENCH_DIR/env/bin/python" ]] || die 'Bench or site is missing'
[[ $BACKUP_ROOT = /* ]] || die 'BACKUP_ROOT must be an absolute path'
[[ -d "$BACKUP_ROOT" ]] || die 'BACKUP_ROOT does not exist'
bench_real=$(realpath "$BENCH_DIR")
backup_real=$(realpath "$BACKUP_ROOT")
[[ $backup_real != "$bench_real" && $backup_real != "$bench_real/"* ]] || die 'backups must be outside the Bench directory'
[[ $HEALTH_URL == http://127.0.0.1:* || $HEALTH_URL == http://localhost:* ]] || die 'HEALTH_URL must point to the local web listener'
for program in bench npm curl git flock; do
  command -v "$program" >/dev/null || die "required command is missing: $program"
done
cd "$BENCH_DIR"
app_dir="$BENCH_DIR/apps/joymedia"
[[ -d "$app_dir/.git" && ! -L "$app_dir" ]] || die 'apps/joymedia must be a separate Git checkout, not a symlink'
[[ $(realpath "$app_dir") != "$(realpath "$BENCH_DIR")" ]] || die 'refusing to deploy into the Bench directory'
exec 9>"$BENCH_DIR/.joymedia-deploy.lock"
flock -n 9 || die 'another deployment is running'

# Build output may be dirty after a prior release. Every other local change is protected.
if ! git -C "$app_dir" diff --quiet -- . ':(exclude)joymedia/public/frontend' \
  || ! git -C "$app_dir" diff --cached --quiet -- . ':(exclude)joymedia/public/frontend' \
  || git -C "$app_dir" ls-files --others --exclude-standard | grep -qv '^joymedia/public/frontend/'; then
  die 'application checkout has local changes outside generated frontend assets'
fi
git -C "$app_dir" fetch --no-tags origin main
git -C "$app_dir" cat-file -e "$target_sha^{commit}" || die 'requested commit is unavailable'
git -C "$app_dir" merge-base --is-ancestor "$target_sha" origin/main || die 'commit is not on origin/main'
old_sha=$(git -C "$app_dir" rev-parse HEAD)
[[ $old_sha != "$target_sha" ]] || die 'this commit is already deployed'

# A running GPU submission or generation run must finish before code/schema changes.
active_attempts=$(bench --site "$SITE" execute frappe.db.count --args '["Generation Attempt", {"status": ["in", ["Submitting", "Queued", "Running"]]}]')
active_runs=$(bench --site "$SITE" execute frappe.db.count --args '["Generation Run", {"status": ["in", ["Queued", "Running"]]}]')
[[ ${active_attempts:-0} == 0 && ${active_runs:-0} == 0 ]] || die "active work remains: attempts=${active_attempts:-0}, runs=${active_runs:-0}"
scheduler_before=$(bench --site "$SITE" execute frappe.db.get_single_value --args '["System Settings", "enable_scheduler"]')
[[ $scheduler_before == 0 || $scheduler_before == 1 ]] || die 'could not read scheduler state'
[[ $(df -Pk "$BACKUP_ROOT" | awk 'NR==2 {print $4}') -ge ${MIN_BACKUP_FREE_KB:-20971520} ]] || die 'backup volume has too little free space'
release_id="$(date -u +%Y%m%dT%H%M%SZ)-${target_sha:0:12}"
backup_dir="$BACKUP_ROOT/$SITE/$release_id"
maintenance=0
switched=0
finished=0
on_exit() {
  local status=$?
  trap - EXIT
  if [[ $finished == 1 ]]; then exit 0; fi
  if [[ $switched == 1 ]]; then
    bench --site "$SITE" set-maintenance-mode on || true
    printf 'Deployment failed after code switch. Site stays in maintenance mode.\n' >&2
    printf 'Backup: %s ; previous commit: %s\n' "$backup_dir" "$old_sha" >&2
    printf 'Restore database/files from the backup before reopening if migration changed schema.\n' >&2
  elif [[ $maintenance == 1 ]]; then
    bench --site "$SITE" set-maintenance-mode off || true
    if [[ $scheduler_before == 1 ]]; then bench --site "$SITE" enable-scheduler || true; fi
  fi
  exit "$status"
}
trap on_exit EXIT

bench --site "$SITE" set-maintenance-mode on
maintenance=1
bench --site "$SITE" disable-scheduler
active_attempts=$(bench --site "$SITE" execute frappe.db.count --args '["Generation Attempt", {"status": ["in", ["Submitting", "Queued", "Running"]]}]')
active_runs=$(bench --site "$SITE" execute frappe.db.count --args '["Generation Run", {"status": ["in", ["Queued", "Running"]]}]')
[[ ${active_attempts:-0} == 0 && ${active_runs:-0} == 0 ]] || die 'work started before maintenance took effect; retry after it finishes'
pending_jobs=$(bench --site "$SITE" execute frappe.utils.doctor.any_job_pending --args "[\"$SITE\"]")
[[ $pending_jobs != True ]] || die 'Frappe background jobs are still queued or running'

install -d -m 700 "$backup_dir"
printf 'old_commit=%s\nnew_commit=%s\nsite=%s\n' "$old_sha" "$target_sha" "$SITE" > "$backup_dir/release.txt"
chmod 600 "$backup_dir/release.txt"
bench --site "$SITE" backup --with-files --compress --backup-path "$backup_dir"
find "$backup_dir" -maxdepth 1 -type f -name '*database*' | grep -q . || die 'database backup was not created'
find "$backup_dir" -maxdepth 1 -type f -name '*private-files*' | grep -q . || die 'private-file backup was not created'
pending_jobs=$(bench --site "$SITE" execute frappe.utils.doctor.any_job_pending --args "[\"$SITE\"]")
[[ $pending_jobs != True ]] || die 'a background job appeared during backup'

switched=1
git -C "$app_dir" restore -- joymedia/public/frontend
git -C "$app_dir" clean -fd -- joymedia/public/frontend
git -C "$app_dir" checkout --detach "$target_sha"
bench setup requirements --python joymedia
(cd "$app_dir/joymedia/frontend" && npm ci && npm run build)
bench build --app joymedia --production
bench --site "$SITE" migrate
bench restart

doctor=$(bench --site "$SITE" doctor)
printf '%s\n' "$doctor"
workers=$(printf '%s\n' "$doctor" | sed -n 's/.*Workers online: \([0-9][0-9]*\).*/\1/p' | head -1)
[[ ${workers:-0} -ge ${MIN_WORKERS:-1} ]] || die 'background workers are not healthy'
if [[ -n ${COMFY_HEALTH_URL:-} ]]; then
  curl --fail --silent --show-error --max-time 10 "$COMFY_HEALTH_URL" >/dev/null || die 'ComfyUI is not healthy'
fi
bench --site "$SITE" set-maintenance-mode off
for _ in {1..12}; do
  if curl --fail --silent --show-error --max-time 5 "$HEALTH_URL" >/dev/null; then
    if [[ $scheduler_before == 1 ]]; then bench --site "$SITE" enable-scheduler; fi
    printf 'Deployed %s; backup: %s\n' "$target_sha" "$backup_dir"
    finished=1
    exit 0
  fi
  sleep 5
done
bench --site "$SITE" set-maintenance-mode on
die 'web health check failed; site remains in maintenance mode'
