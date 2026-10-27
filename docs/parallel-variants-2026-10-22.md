# Two-variant production on the current server

The current host has one NVIDIA RTX PRO 6000 (96 GB) and one ComfyUI process.
ComfyUI accepts multiple prompts but executes one prompt at a time in that
process. A second simultaneous video inference stream is not available on this
deployment. Do not describe queued ComfyUI prompts as parallel GPU rendering.

The application now runs two variants of one creative batch through different
stages concurrently. A dedicated `joymedia_planning` worker writes scripts;
the long worker advances existing storyboards and native generation runs. A
configurable two-variant admission limit prevents a large batch from filling
the queue all at once. Planning jobs carry their target variant index so a
retry cannot process another variant's row. Script-created scene names are
made unique before workbook import, including when resuming a saved script.

Live verification used an isolated reference project owned by
`uitest@example.com`, `PRJ-02622`, with Shera product, mascot, environment and
motion references. It did not change the selected Shera production edit.
Batch `CRB-00038` created two different scripts and two distinct projects:

| Variant | Project | Native first-frame run | Observed state |
| --- | --- | --- | --- |
| 1 | `PRJ-02625` | `RUN-00937` | Keyframes while variant 2 was planning, then both runs active |
| 2 | `PRJ-02626` | `RUN-00938` | Planning while variant 1 rendered, then both runs active |

The planning worker started variant 2 at 20:28:45 UTC. The long worker resumed
variant 1 at 20:30:29 UTC. Both variant records were `Planning` at the same
time; variant 1 then reached `Keyframes` while variant 2 still planned. Both
native runs subsequently held active ComfyUI attempt IDs. This demonstrates
concurrent Frappe jobs and stage overlap, not simultaneous GPU inference.
ComfyUI `/history` returned `success` with outputs for prompt
`02301ef0-9866-4310-b0fc-f614d13e6360` from variant 1 and prompt
`7a927b86-1116-4c74-a1ad-4f4ade298ecb` from variant 2. Their later
reference-retention checks remain separate from raw prompt completion.

The initial 10-second smoke batch (`CRB-00037`) was cancelled after its first
script failed the existing causal/director gate. In `CRB-00038`, the first
script initially reached workbook import with duplicate scene names; the
shared generated-script naming fix was applied, and the saved script resumed
without paying for a second writer call. Some first-frame attempts in both
projects were rejected by the existing product-count safeguard, which reported
two product candidates. Those scene results are
quality findings, not evidence of concurrent execution failure. The native
redraw/review path must resolve them before either video can be exported. After
the concurrency proof, the isolated assisted batch was cancelled to release the
GPU; no video export was requested from this smoke test.

Validation: 111 tests in `joymedia.tests.planning.test_creative`, Ruff, the
Vue production build, a running planning worker and HTTP 200 from the product
web. The live batch IDs and native run IDs above are the source of truth for
this deployment; video quality or completion is not inferred from queued jobs.
