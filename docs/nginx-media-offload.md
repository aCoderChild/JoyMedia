# Nginx media offload for the GPU demo

Installed 30 October 2026 on the public demo backed by Gunicorn at
`127.0.0.1:18080`. The local development server on port 8000 is separate.
The versioned configuration is `deploy/demo-systemd/nginx.conf`.

| URL | Handler |
| --- | --- |
| `/assets/` | Nginx reads `bench/sites/assets`; hashed JoyMedia JS/CSS/font bundles are immutable for one year, other assets revalidate after one hour. |
| `/files/` | Nginx reads `bench/sites/demo.localhost/public/files`; missing files return 404 without Python. |
| `/private/files/` | Frappe checks the existing session and File permissions; successful `X-Accel-Redirect` responses hand byte transfer to Nginx. |
| `/protected/private/` | Internal-only alias for the site's private directory; direct HTTP requests return 404. |
| `/socket.io/` | Dedicated Frappe Node realtime server over a private Unix socket, including WebSocket upgrade and polling. |
| API, login, project pages and other dynamic URLs | Gunicorn; no shared proxy cache. |

Nginx uses `sendfile`, normal conditional requests and byte ranges for seeking.
It preserves Frappe's private cache policy, with a private/no-store fallback
when the upstream supplies none. Uploaded HTML/SVG/XML and other active-content
formats retain forced-download behavior; application SVG assets remain usable.
Public/private media aliases reject symlinks and directory listing is disabled.
The internal private alias is never an unauthenticated public file route.

Access logs record upstream address, body length and timing. Query strings,
cookies and authorization headers are excluded. This also avoids logging the
session query used internally by this deployed Frappe version's realtime
client. The existing Node v20.19.5 runtime satisfies the deployed Frappe's
Node >=18 requirement; no new Node download or app dependency install was needed.
The realtime service explicitly sets `FRAPPE_BENCH_ROOT` because Frappe lives
outside the Bench's conventional physical directory layout.

## Reinstall and rollback

On the GPU host, copy the files under `deploy/demo-systemd` together and run:

```sh
bash deploy/demo-systemd/install-nginx.sh
```

The installer checks Nginx syntax, backs up the previous configuration, installs
and enables `joymedia-demo-socketio.service`, adds a soft startup dependency to
the proxy, then atomically replaces the configuration and gracefully reloads
Nginx. It waits up to 30 seconds for the new routes: Nginx's reload command only
sends a signal, so an immediate probe can still reach an old worker. API,
asset and Socket.IO checks must pass; otherwise the previous Nginx configuration
is restored and reloaded. Backups are named
`/home/ubuntu/joymedia-demo-staging/nginx.conf.before-offload.*`.
The installer targets this demo's existing paths and site name; adapt them
before using it for another Bench or site.

The demo's `install-recovery.sh` calls this installer first, so subsequent demo
setup/recovery deployments include the same proxy and realtime routing. The
deployment bundle is installed with the demo app under
`/home/ubuntu/joymedia-demo-staging/app/deploy/demo-systemd`; it is not dependent
on temporary files under `/tmp`. Reapply the demo infrastructure with:

```sh
bash /home/ubuntu/joymedia-demo-staging/app/deploy/demo-systemd/install-recovery.sh
```

To restore a chosen backup manually, copy it to a temporary file beside
`nginx.conf`, run `nginx -t -c` against that file, atomically rename it over
`nginx.conf`, then run `sudo systemctl reload joymedia-demo-proxy.service`.
Gunicorn and GPU model services do not need restarting.

## Live evidence

Workspace reports are under
`/workspace/development/verification/nginx-offload-20261030`.
A candidate on loopback port 18082, the active proxy on 18081, and the public
HTTPS Funnel URL each passed the same 28 integration checks. They cover exact
file bytes, Unicode filenames, HEAD, ETag/304, public/private Range responses,
a real MP4 seek, guest and unrelated authenticated-user denial, spoofed headers,
internal-path and symlink denial, forced-download SVGs, API routing, and an
authenticated WebSocket namespace connection. Temporary File records, file
bytes and QA sessions were removed after each verification run.

For a 1,620,000-byte public fixture, the active access log recorded
`upstream=-`. For the same-sized authorized private fixture it recorded
`upstream=127.0.0.1:18080 upstream_bytes=0`, while Nginx sent all 1,620,000
bytes. This demonstrates file-transfer offload; private requests still require
one authorization call to Frappe. Both Gunicorn's PID and the Nginx master PID
were unchanged across deployment. The former repeated Socket.IO 404 responses
of roughly 328 KB now reach the realtime server instead.

References: installed Frappe `send_private_file`, `find_file_by_url` and realtime
middleware; [Nginx internal locations](https://nginx.org/en/docs/http/ngx_http_core_module.html#internal),
[upstream response handling](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_ignore_headers)
and [WebSocket proxying](https://nginx.org/en/docs/http/websocket.html).
