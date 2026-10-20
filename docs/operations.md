# Operating JoyMedia

JoyMedia plans with a configured text-capable endpoint, analyses images with a
configured vision endpoint, and renders with ComfyUI on a separate GPU server.
Install the Frappe app first, then configure the required workers and external
services.

## Workers

```bash
bench set-config -g workers '{"joymedia_render": {"timeout": 10800}}' --parse
bench worker --queue short,default
bench worker --queue long
bench worker --queue joymedia_render
```

Run the workers under Supervisor or systemd in production. The render queue
isolates long scene renders and exports from short interactive work.

## GPU tunnel and service configuration

`deploy/joymedia-tunnel.sh` forwards the planner (8001), vision model (8002),
and ComfyUI (8188). Set `JOYMEDIA_GPU_HOST`, `JOYMEDIA_GPU_PORT`, and
`JOYMEDIA_GPU_KEY` for the GPU host and SSH key. Configure the site to use the
forwarded ports:

```bash
bench --site <site> set-config comfyui_base_url http://127.0.0.1:8188
bench --site <site> set-config comfyui_api_key '<COMFY_ORG_API_KEY>'
bench --site <site> set-config joymedia_planner '{"base_url":"http://127.0.0.1:8001/v1","model":"planner"}' --parse
bench --site <site> set-config joymedia_vision '{"base_url":"http://127.0.0.1:8002/v1","model":"vision"}' --parse
```

Keep credentials in site configuration, never in source files or ComfyUI
workflows.

To install the GPU-host services after copying `deploy/` to that host:

```bash
sudo JOYMEDIA_TUNNEL_USER=<ssh-user> ./deploy/install-gpu-services.sh
```

The installation registers generic planner, vision, and ComfyUI system profiles.
Their complete, shell-safe command argv values live in
`/etc/joymedia/runtime.json`; model selection and provider flags are deployment
data, not source code. `runtime.example.json` is a starting profile for the
current host and may be replaced without changing JoyMedia. Once installed,
`bench start` starts the profiles idempotently through the tunnel before opening
forwarded ports. Set `JOYMEDIA_GPU_AUTOSTART=0` to disable that behavior.

Choose a vision profile with enough context for one reference image and its
structured analysis. The review service deliberately sends one image and one
question per request for repeatable judgments.

## Capacity

Exports decode and encode several 1080p/1440p streams with ffmpeg. Allocate at
least 8 GB of RAM (16 GB when exports overlap) and 20 GB of free disk. Set the
planner profile's context window to accommodate the longest approved brief and
its reference metadata; shorter windows can force planning retries.
