#!/usr/bin/env bash
# Keep the SSH tunnel to the GPU server open: the planner (8001), the vision
# model (8002) and ComfyUI (8188). JoyMedia cannot plan or render without it.
#
# Runs in the foreground and reconnects whenever the connection drops, so it can
# be a Procfile/supervisor process. While another tunnel already holds the ports,
# ssh exits (ExitOnForwardFailure) and this loop simply retries later.
#
# Override with JOYMEDIA_GPU_HOST, JOYMEDIA_GPU_PORT and JOYMEDIA_GPU_KEY.

HOST="${JOYMEDIA_GPU_HOST:-ubuntu@50.35.188.78}"
PORT="${JOYMEDIA_GPU_PORT:-30260}"
KEY="${JOYMEDIA_GPU_KEY:-$HOME/.ssh/joymedia_remote}"

while true; do
	ssh -N -i "$KEY" -p "$PORT" \
		-L 8001:127.0.0.1:8001 -L 8002:127.0.0.1:8002 -L 8188:127.0.0.1:8188 \
		-o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
		-o ConnectTimeout=20 -o BatchMode=yes "$HOST"
	code=$?
	echo "$(date -Is) joymedia tunnel closed (exit $code); reconnecting in 10 s"
	sleep 10
done
