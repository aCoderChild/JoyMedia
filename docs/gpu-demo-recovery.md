# GPU demo availability

Recovery installed on 29 October 2026 (Asia/Ho_Chi_Minh).

The GPU demo runs independently of the developer workstation under systemd at
`/home/ubuntu/joymedia-demo-staging`. The original public link failed because a
Cloudflare Quick Tunnel restart allocated a different hostname. A Quick Tunnel
cannot preserve its hostname across restarts.

## Installed recovery

`deploy/demo-systemd/install-recovery.sh` installs the HTTP health timer and
systemd overrides without restarting the existing web services or tunnel.
The web, proxy, Tailscale daemon, scheduler, and five worker queues are enabled at boot.
The installer changes hard runtime dependencies to startup recommendations in
the full unit files (systemd cannot clear dependencies using a drop-in).
It preserves the original files with a `.before-recovery` suffix.
Overrides disable start rate limiting so
services keep retrying after database or network outages. Existing dependency
ordering remains in place.

Every minute, the health timer checks the Frappe ping API, the project page via
nginx, and Tailscale's online status. After three consecutive
failures, it restarts the affected service. An upstream failure restarts the web
service first. It never restarts GPU models or workers with active jobs.
State lives at `/var/lib/joymedia-demo-health/state.json`.

The fallback Cloudflare tunnel metrics address is `127.0.0.1:20241`. The
Cloudflare Quick Tunnel is disabled after migration to Funnel.

## Stable address: Tailscale Funnel

The user selected a `ts.net` address without purchasing a domain. Tailscale
1.104.4 was downloaded from its official stable distribution and its SHA-256
was checked against the published checksum. The GPU container lacks
`/dev/net/tun`, so `deploy/demo-systemd/tailscaled.service` runs it in userspace
mode as `joymedia-tailscaled.service`. State is persisted at
`/var/lib/tailscale/tailscaled.state`; preserve this state and the machine name
to preserve its identity. This protects process restarts, not deletion of the
GPU container or its storage.

Account sign-in completed. The registered machine is
`joymedia-studio.tail8e28b7.ts.net`. Funnel activation completed and the public
project page and ping API were verified over HTTPS. Restarting the Tailscale
daemon preserved the Funnel configuration and the same public hostname.
The machine key currently expires on 27 April 2027 (Asia/Ho_Chi_Minh); disable
key expiry for this server in the admin console for unattended availability.

Setup commands:

```sh
sudo tailscale up --hostname=joymedia-studio --accept-dns=false --accept-routes=false
sudo tailscale funnel --bg http://127.0.0.1:18081
sudo tailscale funnel status
```

The Funnel command may present another browser link to approve HTTPS and Funnel
for the tailnet. Follow it using the account administrator. Disable machine key
expiry for this server in the Tailscale admin console to avoid periodic login
interruptions. Funnel's background configuration persists across daemon
restarts. Only nginx is published; GPU and database ports stay local. Funnel
has provider bandwidth limits and is not an uptime guarantee.

The existing app login remains required. The root-owned
`/etc/joymedia-demo-funnel-enabled` marker switches the health timer to Tailscale
and recovery of `joymedia-tailscaled.service` instead of Cloudflare.

Alternative: a named Cloudflare Tunnel with an owned domain can use
`tunnel-named.conf.example`. Store its token root-owned, mode 0600, and install
the override as `zz-named.conf` so it sorts after `metrics.conf`.

## Verification and limits

- Deployed project page and ping API returned HTTP 200 through the public tunnel.
- Deliberately killing the Gunicorn master resulted in automatic recovery within
  eight seconds; nginx and the tunnel stayed active, and ping returned `pong`.
- Health-check threshold tests verified no restart on one or two failures and
  the correct recovery target on the third failure for each service.
- systemd verified the new health service/timer; the timer is enabled and active.
- No whole-server reboot was performed because it would interrupt GPU jobs.
- Root filesystem was 96% full with approximately 5.8 GiB available. Existing
  media was preserved. Capacity still needs monitoring and expansion or an
  agreed retention policy for sustained generation.
- The permanent address is active. Disabling the server's Tailscale key expiry
  remains an account administrator action.

Useful commands:

```sh
systemctl is-active joymedia-demo-web joymedia-demo-proxy joymedia-demo-health.timer joymedia-tailscaled
sudo systemctl start joymedia-demo-health.service
sudo cat /var/lib/joymedia-demo-health/state.json
sudo tailscale status
sudo tailscale funnel status
```
