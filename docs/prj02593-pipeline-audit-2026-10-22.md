# PRJ-02593 → automatic pipeline audit (22 October 2026)

Scope: live Frappe records for `PRJ-02593`, its automatic child `PRJ-02618`,
`CRB-00033`, frozen runs `RUN-00920/00921`, their video prompts, the current
planning/route/dispatch code, the decoded-frame contact sheet, and targeted
regression suites. This is an audit of a review-export workflow, not a release
approval or a claim that all repository modules were exhaustively proven.

## Answer

The transport runs end to end, but the earlier Shera corrections are **not
applied reliably** to a fresh automatic film. `PRJ-02618` completed a 30-second
preview through real Frappe → first-frame → Ref2VA → audio → export jobs. Its
screenplay uses a tissue before extracting it, the direct video prompt repeats
that contradictory opening/action state, moving package print and mascot
proportions remain unverified, and the camera does not reproduce the intended
reference grammar. Completion currently means a viewable review export.

| Boundary | Verified | Gap / blocker |
| --- | --- | --- |
| Input/version | `PRJ-02593` is a completed review cut (`ASTV-05069`) at 720×1280/30 s; `PRJ-02618` is a separate completed automatic version (`ASTV-05372`). | Source `PRJ-02593` is still `storyboard_approval_status=Draft`; shot 5's selected source-art logo insert conflicts with its disposal name/imported workbook and the source brief's water-absorption/disposal wording. Automatic batch does not inherit that authored storyboard as an example: `CRB-00033.example_workbooks=[]`, `direction=""`. |
| Old feedback | Eleven open/investigating root-family feedback records were snapshotted. | All eleven were classified `Historical`, with zero `Current` notes. `draft_script` passes only `Current` notes to the writer/reviewer. The old issues remain visible as records, but their applicability was neither mapped to this new cut nor enforced as acceptance criteria. See `api/creative.py::_review_context`. |
| AI screenplay | Schema, timed phases, source roster, reference analysis, camera grammar and causal-review prompts exist. | Accepted live scenes 2/3 press/use a white tissue before extraction. The stored `action_review` still has a scene-4 claim contradiction and `director_notes`; automatic mode proceeded. Later reviewer-code tests do not retroactively repair this frozen run. |
| AI storyboard | `prepare_batch` writes an XLSX through the existing template/importer, then `_plan_project` generates per-shot descriptions and first-frame instructions. Six first frames were delivered. | Storyboard inherits the defective script. A separate generated ending image for the *same* shot is not produced/qualified, so automatic FL2VA routing cannot use storyboard text as a last-frame asset. |
| Video execution | `RUN-00920` and `RUN-00921` completed six native tasks each. All frozen shot routes are `PIPE-00058/WF-02690` (Ref2VA). The output decoded and played in the owner browser. | A successful node/job says nothing about action physics, print fidelity or camera geometry. The shot-3 submitted prompt says a tissue is already pressed on the table and then asks the paw to lift it from the pack; its reference-image description also contains unverified package wording. |
| FL2VA/source art | `PIPE-00065` exists and route tests cover explicit endpoint selection. Exact source-art holds and an unselected source-motion candidate exist. | `joymedia_endpoint_generation_pipelines` is absent from site config, and no shot in either project has a `last_frame` reference; FL2VA is not active. The real FL2VA smoke clip followed endpoints but morphed tissue action and altered the pack. Source-art exactness is limited to eligible inserts, not moving Ref2VA frames. |
| Camera/brand/physics | Structured shot policy separates camera from action; source project contains DOCX/hoodie grammar metadata and Shera references. | The automatic preview's observed opening is mostly a push toward a seated bear, not the requested cinematic hook. Source-to-frame package/mascot consistency, contact sequence, and printed `400 TỜ / 4 LỚP` across moving frames have not passed a continuous-video audit. The five-take contact sheet shows changed scale and staging. |
| Finish/release | Automatic mode selected current-run takes, generated sound/music and exported a preview without manual approval stops. | It explicitly freezes `quality_review=deferred`. It does not grant brand/release approval. The selected music exists, but no listening sign-off establishes that the old dullness complaint is solved. |

## Case specificity and hard-coded assumptions

There is no production branch keyed on the literal Shera product name, and the
batch carries selected product/mascot images, duration, output dimensions,
workflow pin and brand data from project input. One hero product per variant is
deliberate, and `create_project` derives ratio from supplied description instead
of imposing 9:16. These are useful case-independent boundaries.

The writer is **not fully case-neutral**. `planning/creative.py` always suggests
the same hook/problem/use/benefit/packshot structure, limits scenes to 2–12,
relies on English action/effect regexes, and uses `the bear mascot` and `the
tissue pack` in generic examples. `planning/production.py` also uses a mascot
example and a mother/baby role explanation. Flexible-pack normalization is
driven by reference analysis but its wording rule explicitly matches a tissue
box. These examples and lexical checks can bias or misclassify a different
product/language. The live generated story was additionally case-specific by
input: it inherited Shera assets, Shera claims, a Shera action reference and a
camera grammar stored on `PRJ-02593`. This is legitimate project data, unlike a
product-name branch in shared code.

The H3 serializer currently emits the same internal five headings for both
image and reference workflows. The MiniMax upstream guides use distinct
base/FL2VA and Ref2VA prompt field structures. The live shot-3 prompt also
appends reference directions after its Audio SFX section. Passing tests certify
the current internal contract; they do not qualify fidelity against upstream
prompt guidance.

## Verification and next acceptance boundary

The current workspace passed 186 targeted tests (creative, film-director, H3,
automatic delivery and routing), Ruff for the inspected Python modules, and a
frontend production build. `bench doctor` reported three workers online.
The repository has extensive unrelated uncommitted changes; these checks apply
to this working tree and live site, not to a verified GitHub commit or deployment.
The previous authenticated run proved native transport and intermediate UI,
but required an initial screenplay retry. No fresh post-fix automatic run was
performed during this audit; current-code behavior beyond those tests is not
claimed as live-qualified.

Before calling the pipeline accurate: (1) reject or repair unresolved causal
and claim contradictions before automatic export; (2) map applicable source
feedback into explicit constraints for the new cut; (3) keep source workbook,
shot metadata and selected footage aligned; (4) inspect continuous output for
identity, printed art, contact physics, support, camera movement and music;
(5) create/qualify same-shot endpoint images before enabling FL2VA for camera
shots; (6) rerun FrappeUI → ComfyUI → export on a fresh Shera version and a
different product/aspect ratio. The release gate remains separate from preview
completion.

Evidence: `verification/prj02593-automation-20261022/` and
`verification/hybrid-routing-20261022/` in the development workspace; see also
`docs/automatic-reference-video.md`, `docs/hybrid-shot-routing.md`, and
`docs/shera-open-issues-2026-10-22.md`.

## Remediation run, 22 October 2026

`CRB-00034` created `PRJ-02619` from selected product, standing mascot,
environment and cinematic motion references. The request explicitly set 30 s
and 720×1280; those are request values, not a pipeline default. The first real
writer run stopped in `Needs Attention` before creating first frames: attempts
1–5 wrote camera-only prose in `action`, and attempt 6 merely changed that to
"pack is visible" in a wide, five-second opening. This is a useful failure of
the automatic quality boundary; it is not a finished film.

The shared writer now tells the model that a camera reveal cannot substitute
for the supplied actor's completed opening interaction, and repair errors say
to replace the action rather than delete camera words. The automatic writer
rejects unresolved causal/director findings after bounded repair and saves its
drafts as private evidence. Cross-scene prerequisite checking catches an
earlier definite item used before it is removed from its source. Historical
family feedback is passed as bounded failure patterns while retaining its
historical scope. Product-reference vision prose that merely claims to read
printed words is excluded from moving-video identity directions. Generated
workbooks carry `generation_origin=ai_director`, so their suggested
`camera_move` does not override the shared structure-based camera policy;
client-authored workbook moves still do. A same-shot ending image is still
required before FL2VA routing, and no unqualified endpoint route was enabled.

The first `PRJ-02619` failure evidence is attached privately as
`rejected-scripts-dfda085f19f22f7c53.json`. The retry also stopped, retaining
`rejected-scripts-9a5c9da438d1079b84.json`: the writer again put a zoom into
the opening and closing `action` fields despite repair instructions. Camera
sentences are now removed safely when a separate physical action survives in
the same timed phase; an empty/camera-only phase remains invalid. A new batch
`CRB-00035` / `PRJ-02620` uses a more explicit opening *project input* (mascot
places the pack), with the same generic writer and verifier. A passing unit
suite does not establish film quality; its first frames, moving shots, sound
and export must still be inspected before claiming the cut meets the brief.

Its first attempt exposed two false positives in shared validation: `dab` was
absent from the completed-contact verb set, and the text reviewer could call a
static pack state “camera in action” without quoting any camera direction. The
action check now includes contact verbs such as dab, pat, blot and apply; the
reviewer drops only a camera-in-action claim whose exact quoted action has no
camera prose. Both have regression tests, and `CRB-00035` was retried after
these repairs. No success is claimed until that retry produces reviewed media.

The retry accepted a six-scene, 30-second screenplay and imported a workbook;
`PRJ-02620` entered the location/first-frame stage. Its causal order is now
place pack → grip/extract one sheet → unfold → cheek dab → disposal → packshot,
with no unresolved director notes. The shared camera compiler gave the opening
wide scene a brisk push-in and locked the precision-contact scenes. This is a
safer camera plan than overriding it with AI-generated `static` cells, but only
one planned shot currently moves; the cut may still feel too restrained. That
quality judgment requires the moving output, not the screenplay alone.

The six real first frames exposed material failures before the video finished:
shot 4 put the mascot's feet on top of the advertised pack while it held a
second blue object, and shot 5 showed the mascot holding a pack instead of the
used sheet beside the basket. The first-frame reviewer missed the support
failure. A targeted live vision query correctly returned true for the obvious
feet-on-pack frame and false for a correctly supported frame. The frame checker
now asks that focused question, starts a bounded redraw on a clear violation,
and automatic delivery waits for those checks and stops if the violation
remains. This does not certify all contact physics: the same vision provider
misread shot 5's pack as a tissue, so that failure is addressed by removing the
container reference from detached-material action shots in future scripts.

The first run also regenerated a generic beige room despite a supplied
Environment image. A single explicitly selected Environment now anchors the
whole film, including close shots named only for its table; the native location
test covers room/table wording. MariaDB error 1020 from concurrent task updates
is now retriable with either MySQLdb or PyMySQL. These fixes apply to new jobs;
`PRJ-02620`'s already-frozen first frames and video run remain diagnostic.
`CRB-00036` starts a new version with the original room, material-only shots
without a package reference, and a motivated carry/tracking beat.

Its first script draft correctly omitted the pack from the three detached-sheet
beats, but strict automatic writing stopped on a localization false positive:
the common loanword “Logo” was treated as untranslated English in Vietnamese
CTA text. The writer is now told to keep physical package lettering out of
`on_screen_text` (source artwork owns it), and the Vietnamese heuristic no
longer rejects four-letter design/brand loanwords while continuing to flag
longer untranslated English. A retry of `CRB-00036` is in progress.

### Result of the next live run

`CRB-00036` accepted seven 30-second scenes and submitted seven real FLUX.2
first-frame jobs (`RUN-00924`) using the supplied living-room reference. It
did **not** produce a new video. The contact sheet at
`/tmp/prj02621-contact.jpg` shows why: scene 3's declared extreme close-up
renders the full mascot and both feet; scene 5 turns the loose used sheet into
a new printed package; scene 7 puts the pack on the floor and the mascot's
feet on/behind it despite the authored side-table packshot. Product lettering
is also regenerated inaccurately. The existing sampled reviewer had called
scenes 3 and 5 `Passed`, so sampled `Passed` cannot be used as a commercial
release verdict. Scene 4 received an advisory `Needs Review` even though the
visible tissue is near the cheek; that contract question needs better timing
semantics before it should block.

The system now checks a cast-bearing close/detail first frame for a whole
visible character body including feet and treats that as critical framing.
Rechecking scene 3 live caught it and queued a bounded redraw. The existing
feet-on-product question caught scene 7, also queuing a redraw. The redraw of
scene 7 removed the feet-on-pack defect, but put the pack on the floor instead
of the side table; the visual admission check marked its geometry unqualified.
Automatic delivery now treats that admission result as critical, preserving
the stop instead of silently animating it. A generic retry instruction for
critical geometry or framing is compiled into subsequent first-frame prompts,
without changing the screenplay or binding the logic to Shera/model names.

Two redraw runs failed at the orchestration boundary: `RUN-00926` was rejected
because the visual admission implementation changed after that frozen run was
created, and `RUN-00927` was prepared during an intermediate source edit and
raised `NameError: _keyframe_retry_direction is not defined`. The final source
now contains the helper and its tests, but these two failed executions are
**not** successful validation. The current candidate remains `Needs Attention`
with no exported video. A fresh keyframe run from the now stable code, then
real video/audio/export jobs and frame-level inspection, are still required.

### Seven-shot render and remaining visual failures

The later native run `RUN-00932` completed seven real H3 Ref2VA clips for
`PRJ-02621`. The screenplay now orders the visible action as pack placement,
single-sheet extraction, unfolding, cheek contact, disposal, pack carry and
product ending. Frappe stores the generated workbook, per-shot descriptions,
first-frame assets and the submitted native tasks. Targeted tests for causal
screenplay checks, reference prompt roles, selected-room reuse and first-frame
geometry pass in the current working tree.

Decoded contact sheets in `verification/prj02621-final-run/` establish that a
completed native run is **not yet** a physically and visually consistent ad.
Shot 3 starts from the selected extraction image but a second sheet appears
while the first is already held. Shot 6 carries the pack yet changes the beige
room to a teal couch during the shot. Shot 7 likewise shifts room palette
before the final product macro. The opening and extraction scenes both spend
substantial time at similar medium scale. Shot 4 has visible cheek contact and
shot 5 puts the used sheet into the basket; these are better grounded than the
earlier wipe attempt. Moving product print remains approximate.

The first-frame stage's bounded redraws did not solve the close-crop, prop and
support failures in scenes 3/5/7. Selected same-shot source controls now
replace those unsafe opening frames. Actual ending controls are supplied for
unfolding and CTA; they make the candidate FL2VA route eligible under the
shared shot router. The endpoint route is configured only for the compatible
base pipeline and still requires a live render/inspection before it can be
called a fidelity improvement. The support image for the carry-to-table
endpoint exists in the source library but has not yet been attached to scene 6.

The first batch resume after `RUN-00932` hit MariaDB error 1020 while selecting
finished outputs. The previous retry behavior unnecessarily queued a new
seven-scene run (`RUN-00933`), which was cancelled before any clip completed.
The recovery code now recognizes wrapped 1020 errors and selects finished
current-run takes before deciding which scenes require GPU work. The seven
`RUN-00932` takes were selected and the project moved to native sound effects,
music and export. This remains a preview in progress; no 30-second exported
asset or satisfactory final cut is claimed here.

Selecting seven takes also revealed a finishing inefficiency: each selection
was requesting post-production immediately, so the first finishing job started
before the last selection and had to repeat its soundtrack pass. Automatic
batch selection now defers that request and queues one finishing job only
after all scene outputs are present. The public single-take action still
requests finishing immediately. Focused native tests cover both paths.

`CRB-00036` then completed a 720×1280, 24 fps, exactly 30.000 s preview
(`ASTV-05424`, `/private/files/PRJ-02621-edited-ece31732.mp4`) with an AAC
soundtrack. The decoded 1 Hz export contact sheet is
`verification/prj02621-final-run/export-contact.jpg`. It confirms the same
unfolding and teal-room defects in the continuous cut. It also shows five
SFX timeline layers, one 31 s BGM source and a voiceover layer; presence of
these layers is not a listening judgment. The project music direction was
revised from generic upbeat wording to a 118 BPM arrangement with named
instruments and event-linked changes. Future automatic screenplay prompts
now explicitly ask for that specificity instead of a mood-only music label.

A first three-scene endpoint attempt (`RUN-00934`) failed before ComfyUI
submission because its ad hoc retry reason was not a valid Frappe select
option. It was cancelled with zero rendered clips. Native take admission now
validates retry reasons before creating a run; a regression test covers this
failure boundary. `RUN-00935` uses the valid `Manual Retry` reason, and its
three video tasks are frozen on `WF-02683` (H3 FL2VA). Its actual outputs
must be examined before replacing the completed preview.

`RUN-00935` rendered all three endpoint-guided scenes. At two samples per
second, shot 6 retains the beige room and follows the mascot carrying the
pack to the side table, and shot 7 pushes from the supported side-table pack
to the supplied close label image, ending on readable `400 TỜ / 4 LỚP`.
Shot 3's first attempt still reversed the physical state: it began with a
sheet already held, moved it back toward the pack opening, then unfolded it.
An attractive endpoint result was not accepted as causal proof.

The actual last frame of shot 2 (the sheet fully extracted and held by the
mascot) was retained as a project image asset `ASTV-05428` and assigned as
shot 3's first frame. Its project storyboard now explicitly states the
already-extracted single sheet at the start, the same sheet unfolded at the
end, and forbids returning it to the pack or drawing another. The storyboard
edit API was extended to accept new start/end states in the same change as
new prompt text; a targeted test proves the Shot controller does not discard
these states during invalidation. `RUN-00936` rendered the one-scene retry;
its 2 Hz contact sheet shows one held sheet moving to both paws and unfolding
without a second extraction. Selected takes are now shot 3 `ASTV-05429`,
shot 6 `ASTV-05427`, and shot 7 `ASTV-05426`. One fresh post-production job is
running with the revised music brief; final export and listening/continuous
cut checks are still outstanding.

### Final selected preview and verification

The second finishing pass completed and exported `ASTV-05446` at
`/private/files/PRJ-02621-edited-135ec914.mp4`. `ffprobe` reports exactly
30.000 s, 720×1280 H.264 at 24 fps and AAC audio. The batch `CRB-00036`
points to that same asset, and the seven project shots retain their selected
takes. Its decoded 1 Hz sheet is
`verification/prj02621-final-run/final-export-contact.jpg`.

Compared with `ASTV-05424`, the selected cut no longer pulls a second sheet
in shot 3 or changes to the teal room in the carry and ending shots. The
subject lifts and opens one previously extracted sheet, dabs the cheek,
drops the used sheet into the basket, carries the pack on the floor-supported
route, and sets it on the side table. The final shot makes a motivated push
from mascot/product to the supplied `400 TỜ / 4 LỚP` source close-up. The
mascot's squat body and flower remain recognizable across these sampled
frames. The new `BGM` asset `ASTV-05445` is tied to the more specific 118 BPM
music brief and is present on the final timeline along with SFX and voiceover.
The export's measured mean/max audio levels are -27.5/-2.7 dB. There was no
human listening pass in this audit, so these metrics do not establish that
the revised score subjectively solves the dullness complaint.

This is a **review preview, not brand/release approval**. The whole moving
package print in the opening/carry shots has not been proven character-perfect
against the source artwork at every frame; only the exact-art ending is
visually grounded. A 1 Hz contact sheet and the isolated 2 Hz action sheets
cannot prove every intervening frame. Frappe's automatic visual review is
still deferred in the automatic-delivery path, as recorded in the batch.
Those are explicit remaining acceptance checks rather than a false `Passed`
claim. For future fully automatic commercials, source-art tracking or a
verified preservation workflow must cover moving package surfaces; a
successful Ref2VA/FL2VA job alone cannot certify printed claims.

The final working tree passed Ruff, `git diff --check`, the frontend Vite
production build, and the full Frappe JoyMedia suite (35 + 708 + 543 tests;
two expected skips). The full-suite run also found and fixed a real UI/API
disconnect: `create_project_from_brief` was called by the new-project dialog
but lacked the required POST whitelist. Three older tests were brought into
line with the now-generic character wording, arbitrary input aspect ratios,
and the revised advisory-plus-critical frame checks. The complete rerun
reported `OK` in all three groups; focused tests for the changed endpoints
and workflow graph also passed.
