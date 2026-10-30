# GPU runtime recovery — 30 October 2026

The three API listeners answered status queries while model work stopped. The
stuck ComfyUI job was `27edde03-cf45-40d4-a3a6-dc34c4ac5f92`, a 73-frame H3
product-view bridge at 640×416. Its last log entry reported a haishare memory
failure during decoding: 4,662 MiB could not be moved off the GPU for another
tenant. This is evidence of shared-memory pressure; a hardware GPU hang was
not established. `nvidia-smi` continued answering.

At inspection the 96 GiB host had about 7 GiB available. ComfyUI's service
accounted for approximately 48 GiB, the planner 27 GiB and vision 17 GiB.
Cgroup counters included 14 earlier OOM kills; their time was not established.
Stopping the three services returned available RAM to approximately 95 GiB.
No host reboot, driver reset, source-image alteration or manual visual approval
was performed.

## Changes applied

- Stopped and restarted `joymedia-comfyui.service`, `joymedia-vision.service` and
  `joymedia-planner.service`, with planner and vision becoming ready first.
  The unprefixed unit names in the incident report are not the running units.
- Added `--cache-none --fast-disk` to the running ComfyUI command through
  `/etc/systemd/system/joymedia-comfyui.service.d/memory-policy.conf`. The
  previous unit and any previous override were backed up under
  `/var/lib/kubelet/joymedia-model-store/runtime/recovery-20261030`.
  The repository's example profile now carries those flags too. Node outputs
  may be recomputed more often; reduced caching trades throughput for memory.
- Removed only rebuildable Yarn/pip download caches, recovering about 0.7 GiB.
  Root storage remains tight: approximately 4.3 GiB free, 97% used. The existing
  media-retention service was run; it found no eligible older copies.
- An attempted environment migration hit a storage allocation limit despite
  the mounted volume reporting free capacity. The original environment was
  unchanged. Only the incomplete destination copy was removed; no migration
  is claimed as successful.

## Actual work verification

Evidence is in the workspace at
`/workspace/development/verification/gpu-recovery-20261030`.

- Planner returned `OK.` through the normal completion endpoint.
- Vision described the supplied source image: a cartoon bear holding a pink
  heart. These are functional image requests, not model-list probes.
- Replayed the exact stuck H3 graph, changing only its output filename prefix
  to a diagnostic folder. New prompt
  `780f8a39-ea7e-4892-91e8-5a1170225a9e` succeeded in approximately 136 seconds
  (133.92 seconds between execution events). Its MP4 is 640×416, 73 frames,
  24 fps, approximately 3.04 seconds, with H.264 video and AAC audio. A complete
  FFmpeg decode passed. The diagnostic output was not promoted into a project.
- Planner and vision passed additional real inference requests after that H3
  workload, each returning within 29 seconds. Available RAM after the job was
  about 45 GiB, compared with 7 GiB before recovery. This demonstrates recovery
  for this workload, not indefinite stability for arbitrary render sizes.

## Batch recovery

CRB-00116 already contained a planner-outage entry in `repair_failures` before
this recovery began. A rewrite in progress later fell through to deferred pose
requirements while the services were stopped. It was restored to `Rewriting`
using the saved, previously pending `scene_revision`. The stopped state and pose
findings were archived in `recovery_events`; creative counters, prior failures,
asset approvals and selected media were preserved. No creative budget reset was
performed. CRB-00117 retained its rewrite and the native automation handoff was
run again. A new native product-view bridge was submitted after recovery.
Neither batch is asserted to have completed export by this incident report.

Do not infer model readiness from `/models`, `/health` or `/system_stats` alone.
For a similar incident, preserve the queue/history, inspect memory and actual
inference, then distinguish an outage from visual rejection before retrying.
