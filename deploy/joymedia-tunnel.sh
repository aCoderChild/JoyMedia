#!/usr/bin/env bash
# Keep the SSH tunnel to the GPU server open: the planner (8001), the vision
# model (8002) and ComfyUI (8188). JoyMedia cannot plan or render without it.
#
# Runs in the foreground and reconnects whenever the connection drops, so it can
# be a Procfile/supervisor process. While another tunnel already holds the ports,
# ssh exits (ExitOnForwardFailure) and this loop simply retries later.
#
# Override with JOYMEDIA_GPU_HOST, JOYMEDIA_GPU_PORT and JOYMEDIA_GPU_KEY.
#
# With JOYMEDIA_GPU_AUTOSTART=1 (the default), the remote services are started
# before the tunnel opens. The SSH account needs passwordless permission for:
#   systemctl start joymedia-qwen.service joymedia-comfyui.service

HOST="${JOYMEDIA_GPU_HOST:-ubuntu@50.35.188.78}"
PORT="${JOYMEDIA_GPU_PORT:-30134}"
KEY="${JOYMEDIA_GPU_KEY:-$HOME/.ssh/joymedia_remote}"
AUTOSTART="${JOYMEDIA_GPU_AUTOSTART:-1}"

ssh_options=(
	-i "$KEY" -p "$PORT"
	-o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3
	-o ConnectTimeout=20 -o BatchMode=yes
)

start_remote_services() {
	[ "$AUTOSTART" = "1" ] || return 0
	if ! ssh "${ssh_options[@]}" "$HOST" \
		"sudo -n systemctl start joymedia-qwen.service joymedia-comfyui.service"; then
		echo "$(date -Is) unable to start GPU services remotely; tunnel will still be retried" >&2
	fi
}

while true; do
	start_remote_services
	ssh -N "${ssh_options[@]}" \
		-L 8001:127.0.0.1:8001 -L 8002:127.0.0.1:8002 -L 8188:127.0.0.1:8188 \
		"$HOST"
	code=$?
	echo "$(date -Is) joymedia tunnel closed (exit $code); reconnecting in 10 s"
	sleep 10
done
