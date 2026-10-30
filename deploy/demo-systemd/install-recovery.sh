#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
# Keep the demo proxy and realtime routes part of every installer run.
bash ./install-nginx.sh
sudo install -m 644 healthcheck.py /usr/local/lib/joymedia-demo-healthcheck.py
sudo install -m 644 health.service /etc/systemd/system/joymedia-demo-health.service
sudo install -m 644 health.timer /etc/systemd/system/joymedia-demo-health.timer
for unit in web proxy tunnel scheduler worker@; do
    # systemd dependency directives cannot be cleared by an empty drop-in.
    # Preserve the original unit and soften dependencies in the full unit.
    service="/etc/systemd/system/joymedia-demo-${unit}.service"
    if [ ! -e "${service}.before-recovery" ]; then
        sudo cp -p "$service" "${service}.before-recovery"
    fi
    sudo sed -i 's/^Requires=/Wants=/' "$service"
    sudo install -d "/etc/systemd/system/joymedia-demo-${unit}.service.d"
    sudo install -m 644 recovery.conf "/etc/systemd/system/joymedia-demo-${unit}.service.d/recovery.conf"
done
# A later named-tunnel override (zz-named.conf) must replace this command.
sudo install -m 644 tunnel-metrics.conf /etc/systemd/system/joymedia-demo-tunnel.service.d/metrics.conf
sudo systemctl daemon-reload
sudo systemctl enable joymedia-demo-web joymedia-demo-proxy joymedia-demo-scheduler
if [ -f /etc/joymedia-demo-funnel-enabled ]; then
    sudo systemctl enable --now joymedia-tailscaled
    sudo systemctl disable --now joymedia-demo-tunnel
else
    sudo systemctl enable joymedia-demo-tunnel
fi
for queue in short default long joymedia_planning joymedia_render; do
    sudo systemctl enable "joymedia-demo-worker@${queue}"
done
sudo systemctl enable --now joymedia-demo-health.timer
sudo systemctl start joymedia-demo-health.service
