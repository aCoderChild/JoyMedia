# Automatic delivery from project references

The project shelf's **New video from these references** action submits a normal
Creative Batch as the signed-in owner. It keeps the project's duration, aspect
ratio, original product/character references, selected motion-reference roles and
pinned workflow. Each video has a new project version; the existing export remains
available throughout generation.

## Delivery modes

`create_product_batch` accepts `delivery_mode` in its request snapshot:

| Mode | Behaviour |
| --- | --- |
| `automatic` | Writes and displays a screenplay, generates and displays first frames, animates them, assembles audio/music and exports a preview without a manual approval checkpoint. This is the default for a new `auto_render=true` request. |
| `assisted` | Retains the existing picture/clip approval flow. This is the default for `auto_render=false` and for older requests without a delivery mode. |

Automatic delivery freezes `automatic_delivery` in each new generation snapshot.
It defers visual admission as a blocking decision for that run; it does not turn
uncertain evidence into a pass or write brand/release approval. Background
consistency observations and production notes remain visible. The final output
uses the existing preview export path. Site-wide quality settings and already
queued runs are not changed.

`services/generation/automation.py` scopes this policy with a context variable.
`services/project/context.py` serializes it at run creation. The ordinary batch,
keyframe, workflow, take, soundtrack and export services still do the work.
The policy is independent of a product name and of the video-model family.

Missing media, invalid input, a corrupt output, unavailable model/service or a
failed encoder is still a real failure. Missing pictures receive the existing
bounded redraws; an automatic failed video run may retry missing scenes once.
No old footage or static frame is silently substituted for an unrendered action.
If a completed current-run take has a source-art warning, automatic delivery may
select it for the preview while retaining its warning and selection provenance.

The screenplay writer keeps the best structurally valid proposal if a later
optional quality rewrite fails. It preserves unresolved director notes and the
rejected-draft evidence; it does not relabel the retained proposal as coherent or
physically verified. A product-only camera paragraph can be normalized into a
stationary product insert; this normalization never replaces a cast actor's action.

## Camera, hook and physical continuity

The writer and workbook carry a structured framing, angle and camera move.
Reference grammar is applied by narrative job, rather than forcing scene 1 to
orbit and every ending to pull back. Precise contact receives stable coverage;
subject travel receives following coverage. Other valid director choices remain.
Different consecutive actions can legitimately need stable contact shots; camera
motion must not hide the operation to create a false impression of variety.

The hook is requested as an immediate tangible event or product reveal. Shot
count and phase timing follow requested duration, actual action and workflow
capacity. No fixed Shera story or universal shot-number rotation is injected.

Alternative pose images remain selectable views of the same identity. The schema
allows one view per identity per shot. Collapsing every pose to the first image
would incorrectly force a seated reference into standing/travelling action.
Reference analysis version 4 records visible pose/support separately from identity,
and per-view preservation constraints reach the writer. Future planning requests
refresh older analyses; frozen runs and their generated frames are not rewritten.
Broad views establish support; close views preserve the working contact area
without requiring the whole body in frame. A continuing grip or carried product
is retained across cuts, rather than reset to a tabletop before every shot.

Example workbooks teach structure and style. Their claims are not automatically
approved claims for another product. Original package artwork and reference
roles remain authoritative; reference conditioning alone cannot guarantee exact
lettering or correct anatomy in every decoded frame.

## Shera qualification

Automatic review delivery can authorize a current screened first frame when its
sole unresolved admission item is the generic `geometry_qualification` caveat.
Every actual observation must be supported, the later consistency check must
contain only that caveat, and the artifact bytes, shot signature, run snapshot
and implementation fingerprint must still match. This narrow handoff applies
only to an explicit automatic **review** request. It preserves Needs Review and
records provisional frame IDs in the batch authorization; it does not grant a
physics pass or release approval. Defects, missing checks, uncertain visual
observations and source-art warnings continue to hold the frame.

The fresh 29 October attempt is CRB-00103 / PRJ-02725, created from PRJ-02724's
original product and mascot inputs. Its live evidence is recorded under
`/workspace/development/verification/fresh-automatic-20261029`; starting it is not
evidence that the full automatic export has completed.

The automatic writer also receives the active source-pixel lock's opening-frame
constraint: a visible package starts each new shot on its support, unobstructed
by an actor. Held-package openings are rejected as incompatible instead of being
silently restaged by downstream product guidance. Existing generated scripts
receive the same preflight on resume. A bounded automatic rewrite retains the
old script/project in history and stops only its own batch-bound first-frame run
before starting a replacement. It never cancels an unrelated project's work.
CRB-00103 exercised this transition from PRJ-02725 / RUN-01358 to PRJ-02726 after
detecting incompatible openings in scenes 2 and 5. No manual approval was used.

An automatic first-frame run whose frozen checker fingerprint predates a hotfix
can be replaced by a new immutable run, at most twice per variant. The original
report/snapshot remain unchanged, and cancellation is restricted to the batch's
own project/run. This is not a seed retry or a reinterpretation of a failed
report. CRB-00103 exercised RUN-01359 → RUN-01360 after support extraction was
fixed to recognize explicit phrases such as “sitting on a cozy rug.” The image
prompt now reinforces foreground floor contact outside table footprints; compact
geometry retries also retain the handled-paper material rule.

The V16 review cut, `PRJ-02593` / `ASTV-05069`, is a 30 s, 720×1280, 24 fps film
with audio. Its source-art inserts preserve printed information. The selected
moving takes and its stale shot-5 disposal label/source metadata do not establish
that the minimal-input automatic path was completed. The earlier detailed issue
snapshot is [Shera open issues](shera-open-issues-2026-10-22.md).

On 22 October 2026, the new shelf action was exercised through a real authenticated
browser at `PRJ-02593` as `uitest@example.com`, creating `CRB-00033` / `PRJ-02618`
with automatic delivery and the project's existing Ref2VA pipeline pin. The first
screenplay attempt failed bounded validation and was retried through the UI. The
accepted retry then proceeded from first frames into native animation without
approval. The later writer-fallback and causal-review fixes passed regression
tests, but this already-running screenplay does not qualify those changes in
a fresh uninterrupted generation.
Execution and visual evidence are recorded under
`verification/prj02593-automation-20261022/` in the development workspace.
An enqueued batch is not evidence of a completed film; inspect its actual run,
provider prompt IDs, intermediate images and exported media before reporting
end-to-end success.

Verification so far: 96 creative/workflow tests, 3 automatic-dispatch tests and
6 reference-analysis tests, 18 ComfyUI transport tests and the two causality/narration regressions passed; the frontend production
build passed. Tests cover mode isolation, immutable snapshot policy, automatic
frame-to-video handoff, preserved assisted review, reference views, timing and
camera/contact priority. No model-quality guarantee is inferred from these tests.

Live inspection also exposed quality defects in the accepted `CRB-00033` draft:
a tissue is used before its extraction scene, several close handling shots repeat,
and the final action touches the packaging while its narration describes tissue
softness. Its first generated image seats the mascot behind the pack rather than
showing the scripted entrance carrying it. These are unresolved quality findings;
automatic completion of that preview must not be reported as proof that hook,
physics, narration/action alignment or brand fidelity has been solved.

## Media transport recovery

`comfyui_upload_fallback_routes` and `comfyui_download_fallback_routes` can map a logical endpoint to an operator-declared
alternate transport of the **same ComfyUI server**. It is not a provider failover.
Only a connection failure or timeout retries the upload; the file is reopened at
byte zero and the generated filename is retained with overwrite enabled. This
makes a lost upload response safe to recover. A download retry requests the same
file descriptor from the alternate transport; it does not regenerate media. HTTP errors are not retried through
another route. Prompt submission retains the native durable attempt identity and
reconciliation; this setting never retries `/prompt`.

The live site's two localhost tunnels terminate at the same GPU ComfyUI port.
The data tunnel intermittently timed out while the control tunnel remained
responsive. The explicit fallback is site configuration, not a hard-coded host in
application code. Old or unrelated workflow endpoints are never redirected.

## Critical findings from the new automatic candidate

These are observations of `PRJ-02618`, separate from the successful job handoffs.
The five-take contact sheet is `five-native-takes-contact.jpg` in the evidence folder.

| Area | Observed evidence | Status / remaining qualification |
| --- | --- | --- |
| Intermediate UI | Six scene descriptions, six loaded first-frame images returning HTTP 200, zero mandatory image-approval buttons, no browser page errors | Verified in the authenticated owner's browser. |
| Reference conditioning | Native attempts bind original product and mascot assets plus each new first frame | Verified binding; moving image identity/lettering fidelity remains imperfect. |
| Camera | Opening mostly pushes toward the seated subject; several later shots also push in; scene 5 pulls back | Does not demonstrate the requested reference's full movement grammar or strong opening hook. |
| Action | Scene 2 brings tissue toward the face despite its described tabletop press; scene 4 shows a cleaning operation | Text-to-action compliance remains unqualified; the physical cleaning result needs continuous-video inspection. |
| Continuity | Body size/material and product-to-mascot scale vary across shots; reference pose constraints were incomplete in old analysis | Version-4 pose analysis and selectable alternative views address inputs in future plans, not already rendered frames. |
| Causality | The accepted screenplay places extraction after first use | Reviewer omission retractions now require quoted prerequisites to occur before the dependent action. Regression covers earlier/later shots and within-shot ordering. This repair does not retroactively repair this running cut. |
| Narration | Reviewer input previously omitted narration/captions; ending action and softness line do not match | Review now receives both fields and asks for concrete action/claim contradictions. Actual rendered alignment remains a separate quality finding. |

Do not close the old owner feedback based on this candidate. Automatic preview
completion removes manual workflow stops; it cannot turn an inaccurate generated
action into a correct demonstration or guarantee commercial quality.

## Completed live execution

`CRB-00033` completed with `PRJ-02618` / `ASTV-05372`:
`/private/files/PRJ-02618-edited-e03723c6.mp4`. Both native runs completed all six
tasks without a failed task. The batch automatically handed images into Ref2VA,
selected only its own current-run takes, generated narration/effects/music and
exported the preview. `PRJ-02501.current_edit` became `PRJ-02618`; the previous
version remains in the shelf.

The signed-in owner's browser downloaded the MP4 with HTTP 200 and played it
with readyState 4, advancing playback time and no media error. Six descriptions
and six first frames remain accessible after completion. It is 30.000 s,
720×1280 at 24 fps, H.264 with AAC audio; a full decode completed without error.
The timeline contains the generated BGM bed, five narration clips and effects
layers. Presence of these tracks is verified; improved musical taste or an
approved listening review is not claimed. The downloaded file and probe are
saved with the execution manifest in the evidence folder.

Targeted checks total 125 passing tests, plus the successful frontend production
build and browser intermediate/output checks. The quality defects above remain
open. The initial screenplay retry is also retained in the evidence: this is a
completed automatic **preview**, not proof of a flawless one-click commercial.
