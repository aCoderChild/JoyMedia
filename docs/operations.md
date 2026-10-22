# Operating JoyMedia

JoyMedia plans with a configured text-capable endpoint, analyses images with a
configured vision endpoint, and renders with ComfyUI on a separate GPU server.
Install the Frappe app first, then configure the required workers and external
services.

For generation that proceeds without manual storyboard/image checkpoints while
showing those intermediate outputs, see
[automatic delivery from project references](automatic-reference-video.md).

For the current Shera film and product-only automation status, including open
release blockers and acceptance checks, see
[Shera open issues (22 October 2026)](shera-open-issues-2026-10-22.md).

## Workers

```bash
bench set-config -g workers '{"joymedia_render": {"timeout": 10800}}' --parse
bench worker --queue short,default
bench worker --queue long
bench worker --queue joymedia_render
```

Run the workers under Supervisor or systemd in production. The render queue
isolates long scene renders and exports from short interactive work.

The scheduler must be enabled (`bench --site <site> enable-scheduler`; `bench start`
runs it in development). A per-minute job syncs ComfyUI attempts and advances
automatic video batches; without it, batches stay at their current stage.

Automatic script writing runs on the `long` queue, one video at a time per
worker (typically 2–4 minutes each). Add `long` workers to write several
batches in parallel.

## GPU tunnel and service configuration

`deploy/joymedia-tunnel.sh` forwards the planner (8001), vision model (8002),
and ComfyUI (8188). Set `JOYMEDIA_GPU_HOST`, `JOYMEDIA_GPU_PORT`, and
`JOYMEDIA_GPU_KEY` for the GPU host and SSH key. By default
(`JOYMEDIA_SEPARATE_COMFY_TRANSPORTS=1`) it also opens separate transports so
large uploads cannot stall control calls: ComfyUI data on 18188, ComfyUI control
on 18189 (`JOYMEDIA_COMFY_CONTROL_PORT`) and vision on 18002
(`JOYMEDIA_VISION_LOCAL_PORT`). Point the site at those ports:

```bash
bench --site <site> set-config comfyui_base_url http://127.0.0.1:18188
bench --site <site> set-config comfyui_control_routes '{"http://127.0.0.1:18188":"http://127.0.0.1:18189"}' --parse
bench --site <site> set-config comfyui_input_dir /path/to/ComfyUI/input   # on the GPU host
bench --site <site> set-config comfyui_api_key '<COMFY_ORG_API_KEY>'
bench --site <site> set-config joymedia_planner '{"base_url":"http://127.0.0.1:8001/v1","model":"planner","max_model_len":8192}' --parse
bench --site <site> set-config joymedia_vision '{"base_url":"http://127.0.0.1:18002/v1","model":"vision"}' --parse
```

With `JOYMEDIA_SEPARATE_COMFY_TRANSPORTS=0`, use 8188 and 8002 instead and omit
`comfyui_control_routes`.

Each separate transport is restarted by the tunnel supervisor if it exits (for
example after the GPU host briefly refuses SSH). If 18188 stops answering while
18189 still does, uploads and submissions fail with "Unable to connect to
ComfyUI" and attempts wait in `Submitting`; they are reconciled automatically
once the port is back. The supervisor also forwards the optional narration proxy
(`joymedia_tts_proxy`, upstream `proxy.py` on the GPU host) on
`JOYMEDIA_TTS_PROXY_PORT` (default 18899; `0` disables it). If that proxy is
unreachable, narration falls back to the direct route once.

On 2026-10-22 standalone respawning 18188 and 18899 transports were started
outside `bench start` (`ps -eo pid,args | grep standalone`); stop them before the
next `bench start` so the supervisor's own transports can bind those ports.

Two more text capabilities are optional. `joymedia_writer` writes automatic
scripts and `joymedia_translator` does faithful translation and rewording; each
takes the same object shape. Without its own entry, `writer` uses the
translator, and `translator` uses the planner.

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

## Deploying a change

After pulling code, run `bench --site <site> migrate` (new workflow versions are
registered by patches and never overwrite a version a past run used) and
`npm ci && npm run build` in `joymedia/frontend` for the editor. Background jobs fork per job and pick
up new Python code on their next job. Do not deploy admission changes while runs
are active; see [architecture](architecture.md).

A new project uses the site's `joymedia_active_generation_pipeline`; a project
keeps the pipeline it was created with.

## Capacity

Exports decode and encode several 1080p/1440p streams with ffmpeg. Allocate at
least 8 GB of RAM (16 GB when exports overlap) and 20 GB of free disk. Set the
planner profile's context window to accommodate the longest approved brief and
its reference metadata; shorter windows can force planning retries. The
automatic script writer sends about 3–5k tokens and needs up to 3k for its
answer, so give the writer endpoint at least 8192 tokens of context.

Rendering dominates batch time: one 30-second automatic video takes roughly
45–60 GPU-minutes (about 1 minute per scene picture and 4–6 minutes per scene
video), so a batch of N videos takes about N times that on one GPU.

See [per-shot render routing](hybrid-shot-routing.md) for the configured endpoint and source-art paths.
