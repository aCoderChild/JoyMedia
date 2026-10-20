# Real UI rendering stress test

`frontend/tests/live-render-stress.spec.js` clicks authenticated studio controls
and submits actual ComfyUI work. Ordinary test discovery skips it unless
`JOYMEDIA_LIVE_RENDER=1` is explicitly set. It forwards real HTTP requests; the
same-scene race uses a forwarding barrier, not a mocked response.

The fixture has seven portrait scenes totalling 30 seconds. The test generates
and approves fresh first frames, cancels an actively rendering GPU prompt, races
two tabs on one scene, overlaps three independent scene runs, regenerates a take,
generates six authored narration cues, and exports the complete edit from the UI. It downloads and fully decodes the
videos, checks frame counts, rate and portrait dimensions, and records hashes.
Brand approval is separate; successful dispatch does not certify visual identity.

Create a separate fixture from an existing test-owned project, from a Bench:

```sh
env/bin/python scripts/create_live_render_fixture.py SITE SOURCE_PROJECT /tmp/live-evidence
env/bin/python scripts/monitor_live_render.py SITE NEW_PROJECT /tmp/live-evidence --seconds 2400
```

Run the monitor in another terminal. It reads only the new project's jobs and
stores ComfyUI queue/history evidence. The fixture utility reuses immutable
reference files and copies starting video versions into the new project's output
assets; it does not copy or fabricate generation jobs. The first frames must be
generated in the new project because project/scene lineage checks are enforced.
Original take selections, approvals and exported films stay in their source
project. The fixture uses native model audio to avoid generating a new music or
foley bed after every intermediate stress take.

From `joymedia/frontend`, provide credentials through environment variables:

```sh
JOYMEDIA_LIVE_RENDER=1 JOYMEDIA_STRESS_PROJECT=NEW_PROJECT \
JOYMEDIA_STRESS_OUTPUT=/tmp/live-evidence \
npx playwright test tests/live-render-stress.spec.js --workers=1 --reporter=line
```

Set `JOYMEDIA_TEST_USER` and `JOYMEDIA_TEST_PASSWORD` securely in the environment;
never commit credentials. `BASE_URL` defaults to `http://127.0.0.1:8000`.

The monitor's `latest-backend.json` must be fresh and belong to the same project.
An absent or timed-out queue response is missing evidence, never proof that a
prompt was cancelled. Cancellation checks require both a Running application
attempt and that exact external prompt in ComfyUI's running queue before Stop.
The test then waits for it to leave the real queue and checks that the previous
take remains selected. Other projects' prompts are never cancelled.

`events.jsonl` records UI requests and downloaded outputs. Backend snapshots and
ComfyUI history retain external prompt IDs, seeds and job lineage. Keep failed
runs in the evidence; distinguish fixture/setup rejection, application errors,
transport delays and inference failures. Measure submission and inference time
separately. Overlapping application runs do not imply parallel GPU inference:
the configured submission capacity and the ComfyUI server determine concurrency.

The measured remote environment uses separate SSH connections for bulk data
(`18188`) and JSON control (`18189`), with both forwarded to the same ComfyUI
server's port `8188`. The existing Procfile tunnel entry starts reconnecting supervisors for both.
The original shared tunnel remains available for frozen historical endpoints.
Configure these mappings only for endpoints known to reach that same server:

```json
{
  "comfyui_base_url": "http://127.0.0.1:18188",
  "comfyui_control_routes": {
    "http://127.0.0.1:8188": "http://127.0.0.1:18189",
    "http://127.0.0.1:18188": "http://127.0.0.1:18189"
  },
  "joymedia_max_active_attempts": 3
}
```

File upload/download stays on the data connection. JSON submission, metadata,
queue/history and prompt-specific cancellation use the explicit control route.
An unlisted historical or alternate endpoint keeps its own address; it is never
silently redirected to the current server. Run evidence retains the logical
endpoint. Three submission slots allow one executing prompt and two queued
prompts on the sequential ComfyUI server, including overlapping input staging
and output ingestion. This does not request simultaneous model inference.

The live test exposed admission/ingestion defects: stale submission
reconciliation could overwrite newer state, a completion between history and
queue reads could be called a lost job, and a queued run without task rows did
not reserve its scene. Recovery now rereads state before promotion; missing-job
detection rechecks history; admission is serialized per project and scene
reservations include the frozen scope immediately upon queueing. Original
failed attempts and the duplicate queued run remain in the evidence.

A final running cancellation is also checked after the narrated export. A stale
background aggregate was able to resurrect Running after Stop, despite the GPU
prompt having been interrupted. Run/task updates now exclude committed Cancelled
rows, and aggregation starts and finishes on fresh state. A 90-second UI refresh
soak and an intentional stale aggregate against the real database verify that
cancellation remains terminal and the completed film stays available.
