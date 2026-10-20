#!/usr/bin/env bash
# Install the GPU services once. Thereafter the Bench tunnel starts them
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

install -d -m 0755 /usr/local/lib/joymedia /etc/joymedia
install -m 0755 "$script_dir/run-profile.py" /usr/local/lib/joymedia/run-profile.py
install -m 0644 "$script_dir/planner.service" /etc/systemd/system/joymedia-planner.service
install -m 0644 "$script_dir/vision.service" /etc/systemd/system/joymedia-vision.service
install -m 0644 "$script_dir/comfyui.service" /etc/systemd/system/joymedia-comfyui.service
if [ ! -f /etc/joymedia/runtime.json ]; then
	install -m 0600 "$script_dir/runtime.example.json" /etc/joymedia/runtime.json
	echo "Created /etc/joymedia/runtime.json; edit it to select the runtime profiles for this host."
fi
/usr/local/lib/joymedia/run-profile.py --validate
systemctl_bin="$(command -v systemctl)"
cat > /etc/sudoers.d/joymedia-gpu-services <<EOF
$tunnel_user ALL=(root) NOPASSWD: $systemctl_bin start joymedia-planner.service, $systemctl_bin start joymedia-vision.service, $systemctl_bin start joymedia-comfyui.service
EOF
chmod 0440 /etc/sudoers.d/joymedia-gpu-services
visudo -cf /etc/sudoers.d/joymedia-gpu-services
systemctl daemon-reload
# Migrate the historical model-named unit when the generic profiles replace it.
systemctl disable --now joymedia-qwen.service 2>/dev/null || true
systemctl enable joymedia-planner.service joymedia-vision.service joymedia-comfyui.service
systemctl restart joymedia-planner.service joymedia-vision.service joymedia-comfyui.service

echo "Installed JoyMedia planner, vision, and ComfyUI profiles. Check with: systemctl status joymedia-planner joymedia-vision joymedia-comfyui"
