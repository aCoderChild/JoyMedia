#!/usr/bin/env bash
# Run on the existing GPU demo host as ubuntu. Reloads only Nginx.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root=/home/ubuntu/joymedia-demo-staging
config="$root/nginx.conf"
node="$root/node-v20.19.5-linux-x64/bin/node"
[ -x "$node" ] && [ -f "$root/frappe/socketio.js" ]
[ -f "$root/bench/sites/demo.localhost/site_config.json" ]
[ -f "$config" ]
candidate="$(mktemp "$root/nginx.conf.candidate.XXXXXX")"
backup="$(mktemp "$root/nginx.conf.before-offload.XXXXXX")"
cp -p "$config" "$backup"
trap 'rm -f "$candidate"' EXIT
cp "$script_dir/nginx.conf" "$candidate"
/usr/sbin/nginx -t -c "$candidate"
sudo install -m 0644 "$script_dir/socketio.service" /etc/systemd/system/joymedia-demo-socketio.service
sudo install -d /etc/systemd/system/joymedia-demo-proxy.service.d
sudo install -m 0644 "$script_dir/proxy-socketio.conf" /etc/systemd/system/joymedia-demo-proxy.service.d/socketio.conf
sudo systemctl daemon-reload
sudo systemctl enable --now joymedia-demo-socketio.service
socket_ready=false
for _ in {1..20}; do
    if [ -S "$root/socketio.sock" ]; then socket_ready=true; break; fi
    sleep 1
done
[ "$socket_ready" = true ]
chmod --reference="$config" "$candidate"
mv -f "$candidate" "$config"
ready=false
if /usr/sbin/nginx -t -c "$config" && sudo systemctl reload joymedia-demo-proxy.service; then
    # ExecReload only sends HUP: old workers can briefly accept connections.
    # Wait for the new routing to answer before declaring failure or rollback.
    deadline=$((SECONDS + 30))
    while (( SECONDS < deadline )); do
        if curl -fsS --max-time 3 http://127.0.0.1:18081/api/method/ping >/dev/null &&
            curl -fsS --max-time 3 http://127.0.0.1:18081/assets/joymedia/favicon.svg >/dev/null &&
            curl -fsS --max-time 3 'http://127.0.0.1:18081/socket.io/?EIO=4&transport=polling' | grep -q '^0{'; then
            ready=true
            break
        fi
        sleep 1
    done
fi
if [ "$ready" = true ]; then
    echo "Nginx reloaded; API, static asset and realtime handshake passed. Backup: $backup"
else
    # Restore atomically; keep the failed configuration for diagnosis.
    cp -p "$config" "$config.failed-offload"
    cp -p "$backup" "$candidate"
    mv -f "$candidate" "$config"
    /usr/sbin/nginx -t -c "$config"
    sudo systemctl reload joymedia-demo-proxy.service
    echo "Offload checks failed; previous Nginx configuration restored." >&2
    exit 1
fi
