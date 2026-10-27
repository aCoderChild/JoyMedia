# Operating JoyMedia

JoyMedia plans with a configured text-capable endpoint, analyses images with a
configured vision endpoint, and renders with ComfyUI on a separate GPU server.
Install the Frappe app first, then configure the required workers and external
services.

For generation that proceeds without manual storyboard/image checkpoints while
showing those intermediate outputs, see
[automatic delivery from project references](automatic-reference-video.md).

For the current one-GPU throughput configuration and its measured baseline,
see [throughput change, 23 October 2026](throughput-one-gpu-2026-10-23.md).

For the current Shera film and product-only automation status, including open
release blockers and acceptance checks, see
[Shera open issues (22 October 2026)](shera-open-issues-2026-10-22.md).

## Workers

```bash
bench set-config -g workers '{"joymedia_render": {"timeout": 10800}, "joymedia_planning": {"timeout": 3600}}' --parse
bench worker --queue short,default
bench worker --queue long
bench worker --queue joymedia_render
bench worker --queue joymedia_planning
```

Run the workers under Supervisor or systemd in production. The render queue
isolates long scene renders and exports from short interactive work.

The scheduler must be enabled (`bench --site <site> enable-scheduler`; `bench start`
runs it in development). A per-minute job syncs ComfyUI attempts and advances
automatic video batches; without it, batches stay at their current stage.

Automatic script writing uses `joymedia_planning` when that worker is online;
the `long` queue is its fallback. Each planning worker writes one video at a
time. The current single-GPU writer service also serves translation, so adding
planning workers alone does not guarantee more scripts per minute.

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

For the temporary setup that hosts the web app on the existing GPU server,
follow the [GPU-host CI/CD runbook](gpu-host-cicd.md). It gates the exact commit
on CI, checks active generation, backs up site data, and fails closed if a
migration or health check fails.

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

The planning worker writes one script at a time while the long worker advances
the other video's visual jobs. A creative batch admits two active variants by
default (`joymedia_active_variants_per_batch`); further variants wait until one
reaches review or completion. `joymedia_max_active_attempts` controls how many
prompts the application can submit, not how many the single ComfyUI process
executes simultaneously. The live site caps submissions at two prompts, allowing
one executing prompt and one staged successor when work is ready. Independent shots within one run retain the
default one in-flight task so product and mascot continuity stays ordered.
On the current one-GPU host, two variants can progress
through different stages at once, but their GPU prompts execute in queue order.

```sh
bench --site <site> set-config joymedia_active_variants_per_batch 2
bench --site <site> set-config joymedia_max_independent_jobs_per_run 1
bench --site <site> set-config joymedia_max_active_attempts 2
```

Real simultaneous clip inference requires another provisioned rendering endpoint
with its own GPU and workflow routing to it.
ComfyUI's [server API](https://docs.comfy.org/development/comfyui-server/comms_routes)
describes `/prompt` as admission to the execution queue, not a promise of
simultaneous inference.

The dispatcher checks the two oldest eligible runs for the currently loaded
workflow and may dispatch one matching run. A second consecutive match ends
that burst, so the oldest waiting run gets the next turn. An unserved run
always goes first. A callback for a different run wakes the selected run
immediately instead of waiting for the scheduler tick. This reduces unnecessary model changes without making one
campaign wait indefinitely.

When an older approved project is rendered again, promotion to the current
site pipeline first checks whether its saved shot references fit the new
first-stage binding contract. If they do not, the project keeps its saved
pipeline; an explicit operator pin still takes precedence. This prevents a
reference-role mismatch from blocking an otherwise valid legacy storyboard.

Automatic batches only redraw failed frames or clips when the latest attempt
was a generation failure. A latest `Input` or `Workflow` failure now stops the
unchanged rerender and asks for revised references, scene instructions or
workflow. The current text reviewer checks acquisition order, action support,
reference roles and camera coverage before generation. It cannot predict a
duplicate package or distorted limb in pixels, so first-frame admission still
screens those images before video inference.

Two source-art preparation diagnostics are exceptions to the otherwise
nonretryable `Input` rule: a generated frame that contains multiple physical
product instances, or whose generated product view cannot be registered to
the supplied source photograph. The source file is still valid in those cases;
the automatic batch redraws only those failed first frames with a new seed,
up to its configured picture limit. An immutable source hash mismatch, missing
input, or workflow error remains nonretryable. No rejected artwork is admitted.

For an explicitly automatic batch, the writer makes bounded repair attempts,
then continues with the best screenplay that passes deterministic schema,
timing and reference validation. Unresolved AI reviewer and localization notes
remain attached to the storyboard as deferred quality findings. A generated
first frame with consistency concerns is likewise retained with its notes for
the review export after bounded redraw; it does not require a click before
video generation. This is preview delivery, not final commercial approval.
Missing artifacts, invalid source bindings, failed workflow execution, and
scenes that cannot be planned remain technical failures with specific retry
actions rather than silently producing a partial video.

Use the read-only report after generating attempts:

```sh
bench --site <site> execute joymedia.services.generation.throughput.report --kwargs '{"hours":24}'
```

The report groups completed and failed attempts by workflow, including
observed queue delay, runtime, known failed ComfyUI execution time and mean input staging,
workflow resolution, prompt submission, output ingestion and visual admission
times. It counts completed video attempts and accepted clips per hour; that is
a generation-step rate, not a finished-commercial rate. It also shows observed
attempt time outside Comfy execution, which can
expose a stalled tunnel, poll, transfer or review queue. New attempts record
these stage timings; older attempts have no stage
breakdown. A completed attempt is a passed generation step, not necessarily a
released commercial. ComfyUI's start and success/error events provide its
execution interval when history contains both; that interval includes graph
work and is not a direct GPU utilization measure. Submission failures and legacy
attempts have no inferred execution interval. ComfyUI does not
provide a historical peak VRAM reading here, so this report makes no peak
VRAM claim.

Small ComfyUI `/history` and `/queue` polls use a 5-second connection and
20-second socket-read timeout. The scheduler leaves a submitted attempt active
on a transient tunnel failure and retries after reconnection. Watch the
separate ComfyUI control tunnel and the non-Comfy attempt time in the report;
a short socket timeout is not a guaranteed wall-clock deadline if the peer
continues sending bytes.

On the current development host, `/workspace` has about 26 GB free and the
Frappe container has about 1.7 GB available RAM. Keep exports to one worker
until the host filesystem is expanded and the container memory allocation is
raised. These resources are owned by the host/container runtime, not by Frappe
queue settings. Avoid clearing project assets merely to admit more work.

See [per-shot render routing](hybrid-shot-routing.md) for the configured endpoint and source-art paths.

## Exact-pixel reference cutouts

The optional studio-reference preparation path uses Meta's SAM 2.1 image
segmenter in an isolated Python environment. This host has the upstream source
at `/workspace/development/upstream/joymedia/sam2` (commit `2b90b9f`) and the
tiny checkpoint at `/workspace/development/verification/sam2.1_hiera_tiny.pt`.
The site settings are `joymedia_sam2_python` and `joymedia_sam2_checkpoint`.
Install `sam2`, CPU or GPU PyTorch, Pillow, NumPy, SciPy and
`opencv-python-headless` in the worker environment, then set both site values.
Do not point the site at the Frappe Python environment; SAM 2's PyTorch
dependencies are intentionally isolated.

The worker masks plain studio images only. It rejects uncertain or rough
outlines, compares output RGB pixels to the source, and asks the visual reviewer
to inspect the matte on a dark background. Prepared cutouts appear as project
reference assets with `subject_cutout` evidence; the source image is retained.
An unverified sheet crop remains an intermediate view until its camera geometry
is reviewed. A clean cutout proves only that source pixels were preserved. The
first-frame visual gate still checks cast count, source fit, scale and support;
it may hold a render for review even when every cutout passed.
