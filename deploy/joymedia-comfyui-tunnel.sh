#!/usr/bin/env bash
# Keep ComfyUI traffic on its own SSH connection. Large planner/vision requests
# must not stall queue checks, prompt submission or output downloads.
# PNG, MP4 and model payloads are already compressed; avoid SSH recompression.
set -u
HOST="${JOYMEDIA_GPU_HOST:-ubuntu@50.35.188.78}"
PORT="${JOYMEDIA_GPU_PORT:-30134}"
KEY="${JOYMEDIA_GPU_KEY:-$HOME/.ssh/joymedia_remote}"
LOCAL_PORT="${JOYMEDIA_COMFY_LOCAL_PORT:-18188}"
REMOTE_PORT="${JOYMEDIA_TUNNEL_REMOTE_PORT:-8188}"
child_pid=""
stop() {
  trap - TERM INT
  if [ -n "$child_pid" ]; then kill "$child_pid" 2>/dev/null || true; fi
  exit 0
}
trap stop TERM INT
while true; do
  ssh -N -o Compression=no -i "$KEY" -p "$PORT" \
    -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=4 \
    -o ConnectTimeout=20 -o BatchMode=yes \
    -L "127.0.0.1:${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "$HOST" &
  child_pid=$!
  wait "$child_pid"
  code=$?
  child_pid=""
  echo "$(date -Is) dedicated ComfyUI tunnel closed (exit $code); reconnecting in 5 s" >&2
  sleep 5 &
  child_pid=$!
  wait "$child_pid"
  child_pid=""
done
