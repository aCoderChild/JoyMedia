# Local UI to final-video verification — 29 October 2026

Later identity, ears, paper material and prompt-format findings are recorded in
[the prompt-guide audit](prompt-guide-audit-2026-10-29.md). The historical review
export below remains evidence of execution, not corrected visual quality.

Deadline: noon, Asia/Ho_Chi_Minh. Verification started around 09:20 local time.

## Acceptance criteria

- Start in the actual local UI with original product and mascot reference uploads.
- Produce and expose an AI script, character pose and product-view preparation, storyboard first frames, native ComfyUI video tasks, scene clips, audio and final export.
- Verify final output by authenticated browser playback, file download, metadata and full decode.
- Preserve existing projects and outputs. Record model-quality failures accurately; do not bypass reference, identity or physical checks to claim success.

## Current run

- Browser created isolated root `PRJ-02723`, batch `CRB-00102`.
- Inputs: original `product.jpg` and `mascot_front.jpg`, uploaded through the Create video dialog.
- Settings: one automatic 15-second portrait 720×1280 video; short tissue extraction and handling brief.
- Evidence: `/workspace/development/verification/pipeline-20261029/`.
- `submission.json` records the actual HTTP request and response; `status.json` and `history.jsonl` retain stage snapshots.

## Checks and blockers

| Check | Evidence | State |
| --- | --- | --- |
| Local web | HTTP 200 at port 8000 | Passed |
| ComfyUI dispatch | Control queue responds, initially idle | Passed connectivity |
| UI reference intake | Real upload, settings and Create videos submission | Passed |
| Creative orchestration regression | 37 tests via site-aware Frappe runner | Passed |
| Script and reference preparation | CRB-00102: script saved; four character scenes have qualified neutral opening support; supplied front product view and cutout retained | Passed after recovery |
| First frames | Five real frames; bounded repair retained model scale/staging findings; operator authorized animation | Available for review |
| Native video | RUN-01357: 5/5, no failed tasks, every selected clip fully decoded | Passed execution; visual review required |
| Audio and export | Four replacement SFX layers, one music bed, five narration tracks; ASTV-06369 | Passed review export |
| Browser playback and full decode | Authenticated HTTP 200 download, full decode, actual monitor playback | Passed |

Previous reports document repeated pose qualification and product-fidelity failures. They remain relevant risks, not findings of this new run. The earlier bare-unittest backend invocation was unsuitable for site-bound Frappe tests; verification here uses the actual configured site.

## Confirmed defects and repairs

1. **Pose false rejection.** A real H3 neutral pose removed the held heart and lowered the paws, but its whole-canvas average change was 0.04984, just below the former 0.05 guard. The guard now requires a meaningful changed region (at least 1% of pixels changing by over 10% mean channel intensity). Identical images and small codec noise still fail; independent pose, anatomy, support, empty-paw, identity, accessory, surface and eye checks remain required. The recovered frame passed all those live checks and was saved as `ASTV-06332`, reference `pose_8c53e58bfffe`. It comes from this run's actual H3 output `30078f6e02_00001_.mp4`, sampled at 2.8s. The original rejected bytes remain in the evidence directory. No synthetic pose approval was written.
2. **Static authored action rejected.** The final scene's inferred `video_prompt` was empty, despite a complete authored static-hold action. Timed-scene planning now assigns the authoritative authored action before normalizing the plan, as it already did afterward. Other prompt requirements remain enforced. The same batch was retried through its UI control.
3. **Supplied reference hidden.** Batch intermediate serialization now resolves a supplied product view to its selected original image, retaining `supplied` provenance. Missing requested angles remain unverified and do not gain a URL.
4. **Automatic intermediates inaccessible.** The RIO header now exposes “View script & outputs” whenever its batch has a script. Assisted script review behavior remains available. A browser regression verifies script and reference visibility without generation requests.
5. **Location model adds tabletop clutter.** All three initial room plates visibly placed books, cups, vases or plants on the required action table. These were genuine rejected outputs, not a false geometry gate. The location prompt now leads with the exposed, continuous tabletop and routes decorative accents to background walls/cabinets, and no longer asks for “lived-in” furnishings. The existing empty-surface and furniture checks remain active. A revised plate passed live qualification after the observer fixes below.
6. **Location observer protocol mismatch.** The revised room had a genuinely bare table, but the observer returned `bbox_2d` in pixels of its resized image rather than normalized `bbox`. The crop path now uses the declared pixel protocol and the exact thumbnail dimensions, retaining compatibility with normalized legacy responses. A second observer returned explicit positive `scale`, `visual_fit` and `placement` fields without an `answer`; all three may establish the combined check only if no summary answer is present. Missing, uncertain or negative components still reject, and a negative summary cannot be overridden. The revised room `4fcb7477a834e1d9-0.png` subsequently passed all live checks and was preserved through the normal location storage path.
7. **Planner validation escaped bounded repair.** A later scene returned an image prompt exceeding the enforced word limit. Normalization raises Frappe's `ValidationError`, but the timed-plan repair loop only caught `ValueError`. It now repairs either validation exception, still failing after its bounded attempts if a usable plan cannot be produced. The error now names the actual word limit rather than incorrectly claiming multiple frames were described. A regression exercises this exception and verifies authored timing/actions survive the repair.

## Validation after changes

- Full site-aware backend suite before repairs: all 153 modules passed, with 1,614 tests across category summaries (the runner reported 1,559 because it counts only one category summary per module).
- Pose module after repairs: 58 tests passed.
- Timed-action module: 10 tests passed.
- Production-planning module: 74 tests passed.
- Location module: 30 tests passed after prompt and observer-protocol repairs.
- Creative module after repair: both plain and site-bound categories passed, including supplied-view regression.
- Browser versions/intermediate flow: four tests passed.
- Frontend utilities: 15 tests passed.
- Frontend production build passed; current built assets are present in the local app.
- Targeted Ruff checks and formatting passed.
- Live ComfyUI inventory: all active image/video/music/effects workflow graphs available, with 1,343 node types registered.

The recovered reusable pose is a neutral opening state, not proof of each later limb gesture. Those gestures are carried by the authored scene/animation prompts and must be inspected in the first frames and final video. Only the supplied front product angle is established by the original input; this run has not qualified unseen package sides.

## Live frame findings

The first native frame prompt was `7facdbef-e45c-47f6-bc03-d4ebedd2d2d5`, task `TASK-02666` / attempt `ATT-02519`. ComfyUI returned a real 720×1280 PNG. The source-art stage replaced its invented package artwork with the original product image before it appeared in the UI. The bear was nevertheless seated on the table rather than the authored rug. Native visual review subsequently flagged implausible package scale on scenes 1–2 and full-body framing in a close action detail on scene 3. Four first frames are undergoing automatic visual correction. These are model-output findings; completed task counts do not establish visual acceptance.

## Deadline demo strategy

The user delegated the choice of demo strategy after being told that visual errors remained. To produce a real review preview rather than continue the same redraw cycle indefinitely, the local UI stopped batch CRB-00102, retaining all its runs and artifacts. The operator then used the normal “Approve image” controls to authorize the five existing generated frames for animation. The API's approval means permission to animate, not a machine physics pass or a release approval; consistency findings remain recorded. The actual UI “Generate video” action returned RUN-01356 at approximately 11:46 local time. No historical rendered footage is substituted for these new clips. This is a UI-driven assisted demo continuation, not evidence of an uninterrupted fully automatic quality-qualified run.

The separate base-model probe failed real execution because the registered base-model weight symlink has no target. That alternative was not promoted. Graph metadata availability alone did not establish model-file availability.

## Review-preview implementation and resource findings

The ordinary full-resolution run RUN-01356 stalled under concurrent GPU and host-memory reservations. Its first provider clip was real and decodable, but a vision-service connection reset prevented admission; no visual pass was inferred from that outage. The run was cancelled with its evidence intact.

At the demo deadline, the workspace gained an explicit **Generate review preview** action. That run froze a deferred-quality, review-export policy in its snapshot. The subsequent consistency hardening below restores visual admission for all new previews. The ordinary API path and permission checks remain unchanged. Three API tests verify policy scope/restoration, permission propagation and rejection of unsupported purposes; four browser tests pass after the UI change.

RUN-01357 was submitted through that UI at 05:08 UTC. Only PRJ-02724 is pinned to PIPE-00069, using existing image workflow WF-02656 and installed eight-step H3 turbo video workflow WF-02695. The project uses 360×640 preview settings. This reduces demo generation time; it does not establish full-resolution visual quality or qualify unseen product angles. The registered alternative base-model symlink was broken and was not selected.

During this recovery, planner and vision services were temporarily stopped for video rendering, with a timed restoration safeguard. Concurrent reservations had left insufficient host memory for H3 offload. The 7B AWQ vision service was reserving 40% of GPU memory for a 2,048-token context; a backed-up systemd override was tested at 12%, which correctly failed its startup KV-cache memory check. The revised candidate uses 18%, two concurrent sequences, 2,048 batched tokens and eager execution. The revised service started and passed a real image-observation request in 2.76 seconds while the planner and MMAudio were running; the planner passed a real text request in 18.96 seconds. A one-second H3 video probe subsequently completed in 29.57 seconds and fully decoded with both services running. This verifies short-preview coexistence, not the earlier full-resolution 20-step profile. The planner reservation remains unchanged.

The finishing helper selects only new clips whose asset provenance traces to RUN-01357, checks their video streams and full decode, then uses the normal take-selection, finishing, narration and review-export services. It cannot silently substitute historical footage. The original AI script remains saved. Scene two's narration was shortened from “Shera tissues are made from 100% virgin pulp.” to “100% virgin pulp.” so its material claim fits three seconds without bypassing the speech-speed guard.

## New video evidence

RUN-01357 completed 5/5 with no failed tasks. The selected clips are ASTV-06342, ASTV-06344, ASTV-06345, ASTV-06346 and ASTV-06347; all fully decode at 360×640 and sum to 15 seconds. `demo-selected-clips.json` records their provenance and probes. Browser observation exposes the script, three prepared assets and five first frames, with no page errors.

Operator inspection of one-second samples (`demo-clips-contact-sheet.jpg`) confirms unresolved staging/package-scale errors in scenes 1–4 and a brown bear in scene 5 instead of the supplied white mascot. This preview demonstrates orchestration and editorial review, not consistent character generation or release-quality advertising. These findings are saved in `demo-visual-findings.json` and are not machine passes.

## Verified final output and demo handoff

- Local workspace: `http://localhost:8000/joymedia/projects/PRJ-02724`.
- Final asset: `ASTV-06369`, `/private/files/PRJ-02724-edited-b8adac7b.mp4`.
- Downloaded artifact: `/workspace/development/verification/pipeline-20261029/final-output.mp4`.
- Export: 15.018 seconds including AAC tail, H.264 1440×2560 / 24 fps, AAC stereo 44.1 kHz, 17,649,147 bytes. The 360×640 scene clips were enlarged by the configured delivery transform; the export dimensions do not represent native generated detail.
- SHA-256: `199177b90c471d7060d4cd138dc0bc11ef2e723e34a0c3d0816278561b9e2d9a`.
- Authenticated download returned 200; FFmpeg decoded the complete picture/audio without errors. Audio is present and peaks at −3 dBFS.
- Actual browser monitor playback advanced beyond 0.5 seconds, readyState 4, no media error and no page errors. Screenshot: `final-browser-playback.png`; evidence: `final-verification.json`, `final-timeline.json`, `browser-observation.json`.
- Workspace reports the current output as `export_purpose=review`, `brand_review_status=Needs Review`, all five shots pending brand review. No release approval was fabricated.
- Both model services and ComfyUI are restored and active. The temporary phase-restoration timer was stopped after restoration. `runtime-smoke.json` verifies live planner/vision inference; `coexistence-probe.json` and its MP4 verify short H3 generation under the revised vision allocation. The repository runtime example includes that verified vision configuration; the remote direct systemd service uses `/etc/systemd/system/joymedia-vision.service.d/demo-memory.conf`.

For the demo, open the workspace, choose **View script & outputs** to show the AI script and reference preparation, inspect the five scene cards, then choose **Watch video** and play the exported review preview. The timeline includes five video clips, five voiceovers, a full-length music bed and four effects layers. The source batch remains cancelled to prevent the earlier automatic redraw loop from overwriting this assisted continuation.

The functional demo path is verified. Uninterrupted automatic visual acceptance is still unresolved: staging/scale and scene-five identity errors remain visible, only the supplied front product view is qualified, the full-resolution profile was not revalidated under the new memory settings, and the alternative base-model file is missing. The final export completed at approximately 12:35 local time, after the original noon deadline.

## Follow-up: block obvious physical and consistency failures

The owner requested detection and avoidance of obvious defects after seeing the review export. New automatic and review-preview snapshots now freeze the configured visual-admission policy, just like assisted runs; preview purpose no longer disables screening. Existing completed runs, reports and the demo video retain their original provenance.

- First frames and sampled decoded/composited video now receive an independent, schema-constrained geometry observation for solid intersections, unsupported stationary weight and clearly implausible relative scale. Missing, malformed or ambiguous evidence remains uncertain. Observed violations block admission and use the existing bounded evidence-directed correction path.
- For an explicit, unambiguous seated/standing opening support, the observer describes the actual actor support without receiving the authored answer. Code compares that observation with the named opening support. Unknown prose, hidden support and actors with differing supports are not guessed. Product-only scenes do not reuse a product's placement as an actor-support instruction.
- Identity comparisons explicitly cover colour, surface material, face design and worn accessories, with held removable props distinguished from identity. Critical identity/style findings now receive the same bounded correction handling as critical physical findings.
- The approval endpoint rejects pending checks and critical findings. An older approval cannot make a critically flagged frame eligible as a generation input. The RIO scene cards display those findings and disable approval/render buttons. Automatic finishing also stops on known critical findings instead of assembling them merely because the export is a preview.

Live evidence is in `/workspace/development/verification/obvious-errors-20261029/`. `admission-scene-1.json` records a complete admission hold: the actor is observed on the table while the authored opening places it on the rug. `admission-scene-5.json` holds the unrequested teddy in a product-only closing shot. Both return Needs Review with review_only=false. A separate exact-source identity comparison (`live-identity-control.json`) rejects the brown textured teddy against the bound white smooth pose. The unoccupied location control returns supported geometry observations. Earlier failed protocol/yes-no experiments are retained; no calibration claim is made from those failures.

Limits remain explicit: these are sampled visual checks, not a physics simulation or a guarantee of all-frame consistency. The short support parser deliberately abstains on unrecognised or ambiguous prose. Relative-scale judgments remain model observations, not measured real-world dimensions. Bounded repair may stop for input/workflow correction instead of producing a film. The existing demo's defects were detected diagnostically; it was not regenerated or retrospectively certified.

Follow-up validation: the review test selection passed all modules (240 tests reported), creative-planning module passed (129 plain tests plus its site-bound category), keyframe-stage module passed 13 tests, automatic-delivery module passed 10 tests, and all five browser workflow tests passed. The production frontend build and targeted Ruff/diff checks pass. Site-bound suites were rerun sequentially after a concurrent test-initialization write conflict in tabSingles; the corrected runs pass and the scheduler remains enabled.

The built localhost UI was also checked with the real account: three retained critical findings appear on their scene cards and those scene-render controls are disabled, with no page errors (`ui-verification.json`, `critical-findings-ui.png`). A direct site-bound approval request for SHOT-02973 was rejected despite its older Approved flag; `approved_keyframe_task` returns no usable input, and the historical flag was left unchanged (`backend-approval-verification.json`). The held-product contact question no longer presupposes a held product and explicitly accepts visible table/floor support, addressing a contradictory legacy finding. Its consistency regressions pass again.
