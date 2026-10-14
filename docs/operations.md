# Operating JoyMedia

JoyMedia plans with Qwen, analyses images with Qwen VL, and renders with ComfyUI
on a separate GPU server. Install the Frappe app first, then configure the
required workers and external services.

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
bench --site <site> set-config qwen_base_url http://127.0.0.1:8001/v1
bench --site <site> set-config qwen_vl_base_url http://127.0.0.1:8002/v1
bench --site <site> set-config qwen_vl_model joymedia-vl
```

Keep credentials in site configuration, never in source files or ComfyUI
workflows.

To install the GPU-host services after copying `deploy/` to that host:

```bash
sudo JOYMEDIA_TUNNEL_USER=<ssh-user> ./deploy/install-gpu-services.sh
```

The installation registers the Qwen 2.5 32B planner, local AWQ Qwen 2.5 VL
vision model, and ComfyUI as system services. Once installed, `bench start`
starts them idempotently through the tunnel before opening forwarded ports. Set
`JOYMEDIA_GPU_AUTOSTART=0` to disable that behavior.

The vision service expects its model at
`/home/ubuntu/models_qwen/Qwen2.5-VL-7B-Instruct-AWQ`. Its bounded 2,048-token
context is sufficient for JoyMedia's single-image analysis and review requests.

## Capacity

Exports decode and encode several 1080p/1440p streams with ffmpeg. Allocate at
least 8 GB of RAM (16 GB when exports overlap) and 20 GB of free disk. Start
the Qwen planner with `--max-model-len 12288`; shorter context windows can
force planning retries.
