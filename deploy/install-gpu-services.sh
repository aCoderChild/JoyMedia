#!/usr/bin/env bash
# Install the two GPU services once. Thereafter the Bench tunnel starts them
# automatically whenever `bench start` is launched.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
	echo "Run with sudo: sudo $0"
	exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
tunnel_user="${JOYMEDIA_TUNNEL_USER:-${SUDO_USER:-}}"
if [ -z "$tunnel_user" ] || ! id "$tunnel_user" >/dev/null 2>&1; then
	echo "Set JOYMEDIA_TUNNEL_USER to the SSH account used by deploy/joymedia-tunnel.sh."
	exit 1
fi

install -m 0644 "$script_dir/qwen.service" /etc/systemd/system/joymedia-qwen.service
install -m 0644 "$script_dir/comfyui.service" /etc/systemd/system/joymedia-comfyui.service
systemctl_bin="$(command -v systemctl)"
cat > /etc/sudoers.d/joymedia-gpu-services <<EOF
$tunnel_user ALL=(root) NOPASSWD: $systemctl_bin start joymedia-qwen.service, $systemctl_bin start joymedia-comfyui.service
EOF
chmod 0440 /etc/sudoers.d/joymedia-gpu-services
visudo -cf /etc/sudoers.d/joymedia-gpu-services
systemctl daemon-reload
systemctl enable joymedia-qwen.service joymedia-comfyui.service
systemctl restart joymedia-qwen.service joymedia-comfyui.service

echo "Installed joymedia-qwen and joymedia-comfyui. Check with: systemctl status joymedia-qwen joymedia-comfyui"
