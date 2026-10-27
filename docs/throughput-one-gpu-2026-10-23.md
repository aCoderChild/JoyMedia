# One-GPU throughput change, 23 October 2026

The live JoyMedia site has four Frappe workers, two active creative variants,
one ComfyUI process and one RTX PRO 6000 GPU. ComfyUI accepted no queued or
running prompts during deployment. The application now permits at most two
submitted attempts at once; an independent run keeps one in-flight shot. A
second prompt may be staged while the first executes. This is queue overlap,
not simultaneous GPU inference.

The dispatcher favors one matching workflow among the two oldest ready runs,
then returns to the oldest run after two consecutive dispatches of that
workflow. Unserved runs keep priority. A callback for a different run wakes
the selected run immediately, without waiting for the minute scheduler.

Automatic batches now stop an unchanged frame or clip rerender after the
latest attempt fails with `Input` or `Workflow`. The existing script reviewer,
reference analysis, run preflight and first-frame gate remain responsible for
their respective text, input, workflow and rendered-image checks. The system
cannot know that a generated image contains a duplicate product before it
renders the image. A changed scene/reference plan is required after that
deterministic rejection; ordinary generation failures still have their
bounded retry path.

The 24-hour attempt baseline at deployment was 115 completed and 176 failed
attempts. Of the failures, 120 were `Input`, 33 `Generation`, 22
`Infrastructure` and one `Workflow`. These are attempt counts, not completed
videos. The observed median queue delay was 1.3 seconds. Historic failed
attempts do not have reliable ComfyUI execution intervals. New attempts store
input staging, workflow resolution, prompt submission, output ingestion,
visual admission and provider execution intervals in `timing_json`; the
read-only report groups them by workflow:

```sh
bench --site joymedia.localhost execute joymedia.services.generation.throughput.report --kwargs '{"hours":24}'
```

This report does not measure peak VRAM or released-video quality. It must be
compared across equivalent workloads before attributing a throughput gain to
workflow affinity or the smaller queue. The report also shows observed time
outside Comfy execution; this includes poll delay, transfer and review, so it
is not a CPU-utilization measurement. The Frappe container had about 1.7 GB
available RAM and `/workspace` about 26 GB free. The Docker host owns those
limits; increasing Frappe worker counts cannot expand them. Keep a single
export worker until host RAM and storage are expanded. The workspace contains
about 8.2 GB of model cache and backups; those are user assets and were not
deleted or moved.

Validation: database migration added `timing_json`; the site reports capacity
two; ComfyUI `/queue` was empty and the project web returned HTTP 200. The
orchestrator, runner, ingestion, admission, ComfyUI client and throughput tests
passed. Two isolated one-frame renders were submitted from test project
`PRJ-02627` through the real Frappe → ComfyUI route; neither changed the
user's selected edit. `RUN-00939` / `ATT-01413` and `RUN-00940` / `ATT-01414`
both completed. The second recorded 9.714 seconds of input staging, 0.518
seconds of submission, 20.133 seconds of Comfy execution, 3.105 seconds of
output ingestion, and 0.021 seconds of visual admission.

That second attempt also exposed a separate reliability issue: its total
attempt duration was about 1,550 seconds. A default worker began refreshing
the run at 01:31:37 UTC and returned a ComfyUI control-tunnel disconnect at
01:49:01 UTC. The SSH tunnels reconnected at about 01:55 UTC; the frame was
ingested at 01:56 UTC. The ComfyUI client previously gave the small `/history`
and `/queue` polls the same 180-second read timeout as transfers. Those polls
now use a 5-second connect and 20-second read timeout and report a transient
connection error without failing an already-submitted attempt. This bounds
normal socket inactivity, but cannot guarantee end-to-end wall time if a
remote peer continues streaming bytes. Monitor tunnel health and the new
non-Comfy attempt-time metric before claiming a throughput improvement.

A third isolated frame on the same test edit verified the ordinary unpinned
route after a legacy-pipeline compatibility guard was added. `PRJ-02627` kept
its saved `PIPE-00058` because the site's older active `PIPE-00050` cannot
accept one of its approved reference roles. `RUN-00941` rendered its first
frame as `ATT-01415`, which visual admission rejected for an unexpected body
part. The one allowed quality correction, `ATT-01416`, passed and completed the
run. The accepted attempt took 52.95 seconds wall time, of which 19.686 seconds
was Comfy execution. This confirms the route and bounded retry, not the
acceptance rate of a full video batch.

Operational limits still outside application code: the mounted `/workspace`
volume has only about 24 GB free, and the app host has about 1.9 GB available
RAM. Storage expansion and a larger host/container memory allocation require
changing the host configuration; no project files or model backups were
deleted. ComfyUI history does not report per-attempt peak VRAM, so the report
leaves that measurement unavailable rather than presenting boundary samples
as a peak.
