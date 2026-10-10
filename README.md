### JoyMedia

AI Video Generation for product commercialization

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app joymedia
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd joymedia
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
# JoyMedia

JoyMedia is an internal product-video workspace. Administrators invite staff
accounts and grant the `JoyMedia User` role; self-registration is disabled by
default. To enable the custom signup flow intentionally, set
`joymedia_allow_signup = 1` in the site configuration.

### Deployment checklist

JoyMedia plans with Qwen and renders with ComfyUI on a separate GPU server. A
production server needs all of the following.

**1. Processes.** Besides the web server, scheduler and socketio:

```bash
bench set-config -g workers '{"joymedia_render": {"timeout": 10800}}' --parse
bench worker --queue short,default            # quick jobs, bursts of cleanup jobs
bench worker --queue long                     # storyboards and scene renders
bench worker --queue joymedia_render          # exports and "Finish film" (up to an hour each)
deploy/joymedia-tunnel.sh                     # SSH tunnel to the GPU server, reconnects itself
```

The development `Procfile` starts all of them with `bench start`. In production,
run each under supervisor or systemd so it restarts when it exits. Each queue has
its own worker so a burst of quick jobs (deleting a project queues thousands)
never delays a storyboard, and an hour-long export never delays a scene render.
Without a `joymedia_render` worker, exports fall back to the `long` queue.

**2. GPU server tunnel.** `deploy/joymedia-tunnel.sh` forwards the planner
(8001), the vision model (8002) and ComfyUI (8188). Set `JOYMEDIA_GPU_HOST`,
`JOYMEDIA_GPU_PORT` and `JOYMEDIA_GPU_KEY` if the server or key changes. The
site config must point at the forwarded ports:

```bash
bench --site <site> set-config comfyui_base_url http://127.0.0.1:8188
# API-node credential used by server-side Flux.2 requests (keep it out of code/workflows)
bench --site <site> set-config comfyui_api_key '<COMFY_ORG_API_KEY>'
bench --site <site> set-config qwen_base_url http://127.0.0.1:8001/v1
bench --site <site> set-config qwen_vl_base_url http://127.0.0.1:8002/v1
```

For automatic startup, install the GPU services once on the GPU host (after
copying this `deploy/` directory there):

```bash
sudo JOYMEDIA_TUNNEL_USER=<ssh-user> ./deploy/install-gpu-services.sh
```

This installs and enables Qwen and ComfyUI systemd services. The Bench tunnel
then runs `systemctl start` idempotently before it opens the forwarded ports,
so `bench start` restores the GPU services and its tunnel after either host
restarts. `<ssh-user>` must match `JOYMEDIA_GPU_HOST` and have the configured
SSH key; the installer grants it only the two required `systemctl start`
permissions. Set `JOYMEDIA_GPU_AUTOSTART=0` to disable this behavior.

**3. Memory.** Exports decode and encode several 1080p/1440p streams with
ffmpeg. Give the server at least 8 GB of RAM, 16 GB if several people export
at once, and keep at least 20 GB of disk free for renders.

**4. Planner context.** The AI director's prompt and plan need more than 4096
tokens; start the planner with `--max-model-len 12288` (the KV cache it already
reserves is large enough). With 4096, plans are retried with shorter prompts.
