# Systematic H3 camera direction

## Current camera ownership

The Brand-sheet `Camera style: cinematic` activates a deterministic policy.
The planner supplies semantic `shot_structure`; application policy derives
`camera_intent`. Inferred camera fields returned by the language model do not
override that policy. Explicit authored camera plans still use strict validation.
One continuous shot receives one main camera behavior, chosen independently of
camera commands embedded in scene prose. The supplied opening frame owns its
actual crop; movement must respect reviewed subject bounds and product margins.

H3 serialization keeps visual direction, reference roles, opening, chronological
action, camera, sound and ending in that order. Timed actions appear once;
event-specific physical checks remain attached to their time window. Reference
fidelity rules preserve existing lettering instead of banning all printed words.
Style appears once. Global style should describe light, materials and mood;
actors, locations, props and physical events belong to individual workbook rows.

Explicit named reference views constrain identity expansion: selecting one pose
must not silently attach every pose of the same identity. Structured framing also
chooses broad or close location context. Empty, declared cast/product cells mean
that role is absent from the shot, including reaction coverage and macro inserts.

Prompt conformance is an intention, not measured footage. Verify decoded motion,
framing, support, action and package artwork before selecting a take. Installed
Ref2VA weights and valid references do not establish release qualification.
Failed or uncertain candidates retain their evidence and prior selected takes.
The running Shera qualification is recorded separately from code verification.

The Brand sheet may also contain `Camera reference grammar`, a version-1 JSON
object with `sources` (name and SHA256), `notes` (observed editing/camera rules),
and `moves` (narrative stage to validated camera intent). This is authored
reference analysis, not an uploaded motion-reference channel. Stage preferences
can select an arc for an introduction or a pull-back for a reaction; precision
contact and extreme close-ups retain their stable demonstration coverage.
Arc and pull-back still require both reviewed boundary images and explicit
reframing permission. Source provenance alone never authorizes a move or proves
physical correctness. Review both endpoints for connected furniture, plausible
seated support and consistent anatomy before animation, then review the actual
rendered motion. A defective starting frame must be replaced along with its
endpoint; a corrected endpoint cannot repair invalid opening geometry.

Implementation boundaries and deployment checks are in [architecture.md](architecture.md).

## Reference-video analysis integration

Inferred reference preferences now resolve against available boundaries before
approval. A spatial reveal without both endpoints can use tracking for locomotion
or a bounded axial push for broad coverage, with the resolution recorded in plan
notes. Explicit authored controls retain their strict endpoint gate. Tracking
maintains crop and does not require push-in margins. An approved, current keyframe
artifact can supply actual framing evidence even without a manually uploaded
first-frame Asset Version. Its frozen artifact travels to the prompt compiler;
pending or stale keyframes cannot authorize a move.

Timed scripts can ground ordinary props, support surfaces, materials and body
parts with exact quotes from their authored action/visual/continuity/place cells.
These can participate in physical relations and checks without an extra reference
photo. Extra actors/products and replacement reference IDs are rejected. The
application still owns event IDs and timing; inferred constraints cannot rewrite
the authored action sequence. Camera movement remains independent of that action.

Motion videos selected in the existing reference picker are analyzed before
storyboard and production planning. The inspector also has **Analyze reference
camera**, which queues the same analysis through the normal long worker. General,
Style, product and output videos do not silently become camera controls.

The analysis core is reused from [CameraPath Lab](https://github.com/Kayariyan28/CameraPath-Lab),
revision `a7d1ddd7c2d78ea772a01ecc612e679034d5da23`, under MIT. Only the
portable video/tracking core is vendored; its import namespace is relocated.
`joymedia/vendor/camerapath/UPSTREAM.json` records original file hashes and the
license is retained. No separate web server, Blender, COLMAP or new GPU model is
required. Install the `cinematography` optional dependency group on planning workers.

`services/intake/cinematography.py` calls the upstream container-PTS probe,
motion-compensated cut detector and two-pass foreground-rejecting motion
analysis. Asset Version analysis retains source SHA256, dimensions, detected
boundaries, pixel-space signatures and warnings. These inform planner context;
they are never relabeled as metric camera paths. Analysis failures stop planning
instead of silently applying an unrelated default. Rendering does not reanalyze
reference footage.

Editorial interpretations remain explicit reviewed inputs. The existing workbook
Brand grammar works, and `joymedia.api.assets.review_project_camera_reference`
can attach that same validated grammar to an analyzed, selected Motion asset.
The video hash must match the analyzed evidence, and the caller needs project
and asset write access. Conflicting stage preferences across selected references
or the workbook are rejected. Camera evidence and reviewed direction are part
of the approved-plan signature, so changing either requires review before render.
Reference grammar is also frozen in the normal generation snapshot. When an
initial storyboard has semantic structure but no explicit camera intent, both
prompt compilers derive it from that frozen grammar. Missing semantic structure
in cinematic mode stops generation rather than reverting to unrelated camera
defaults. Initial plans, revisions, appended scenes and production replans all
receive the same source context.

The article's vocabulary is separated into framing, angle/perspective and motion:
pan/tilt rotate; truck/pedestal/dolly translate; zoom changes focal length.
The shared camera compiler now accepts directional pan, tilt, truck, pedestal
and zoom in addition to existing locked, axial, tracking and arc moves. New
reveals require both reviewed endpoints and explicit reframing permission.
Contact demonstrations retain the existing stability guard. Speed phrasing now
applies to arc/reveal moves as well as axial pushes. The same decisions feed H3
and the plain prompt adapter; no provider or product identifiers select moves.

The DOCX's four editorial rules remain in `director_rules.CINEMATOGRAPHY_RULES`
and previous-shot coverage context: motivated shot-size changes, pacing by
information/action, the 180-degree axis with match action, and geography →
action → feeling. They guide planning rather than mechanically alternating
sizes or overriding authored timing, approved images or output aspect ratio.
Visual continuity still requires reviewing the rendered footage.

Reference verification: the supplied hoodie master has 620 frames at 24 fps,
1440×2560. Both PySceneDetect and the integrated CameraPath detector find one
continuous shot. The observed introductory viewpoint change, product-detail
coverage, widening city view and final floating-product view are visual phases,
not four detected cuts. The tracking result did not establish a 3D path;
the active H3 workflow receives compiled text and supported image inputs, not
an invented pose or reference-video channel.

The sections below retain earlier policy and qualification context.

Authored format and coverage authority are documented in [input-authority.md](input-authority.md).
The active compiler no longer invents a framing cycle by shot number. Optional
workbook coverage fields constrain inferred structure; camera behavior remains
derived by shared policy. A broad push with both reviewed boundary images
follows those compositions. Without those anchors, unknown/tight framing stays
locked. Precision handling still remains locked even when endpoints are supplied.
The scope of this exception is an authored spatial move, not permission to crop
arbitrarily or to bypass review of the rendered result.



H3 video tasks use the existing JoyMedia scene compiler, with a provider-specific
serializer in `services/planning/h3.py` and shared camera decisions in
`services/planning/camera.py`. Both pipeline and direct-workflow preparation pass
the actual workflow to the compiler. Detection uses executable H3 node types,
not workflow names or project-specific rules. Image stages and other video
providers retain their existing serialization.

## Authoring and output

A scene needs its subject/action and references; it does not need a `Camera:`
paragraph. H3 receives visual direction, reference roles, opening, chronological
action, one camera behavior, authored dialogue, and ending in that order.

I2VA/FL2VA serialization includes first/last-frame alignment followed by
`integrated_multimodal_description`, `overall_soundscape`, and
`non_diegetic_music`. The registered Ref2VA path uses the reference model's six
fields. It describes only the opening image and optional product image actually
accepted by that graph. Library references are not falsely described as extra
uploaded images/videos. Adding a reference video or voice-control channel still
requires a workflow that accepts and binds it; prose alone does not supply media.

Named dialogue supplied in an `Audio: ...; Dialogue: ...` channel stays with the
visual timeline, including exact quoted words or existing H3 `<d>` tags. Sound
effects and ambience go in the soundscape; labelled music goes in the music
field. Effects-only modes retain the existing speech/music suppression policy.
A separately recorded voiceover is not copied into the model's dialogue.
Missing music is `N/A`; the compiler does not invent a score.

## Camera policy v2 — framing before movement

The first opening-frame image is assessed with the existing vision client.
The assessment locates all primary subject components together, records whether
those components are fully visible, and is cached against the image bytes,
vision model/revision and assessment question. Pixel bounds are normalized
against the actual downsampled image sent to that client. Invalid, unavailable
or ambiguous grounding never authorizes a push-in.

- A move requires a complete subject with at least 8% clear margin on every
  side. A tight or already cropped opening, or an opening not yet available
  for assessment, receives a static camera.
- Explicit preservation locks, split screens, product contact events and closing
  holds also require a static camera. Product demonstrations retain fixed focus.
- Eligible reveals receive one centred, very slow push-in requesting at most 2%
  apparent enlargement, followed by a final hold. No automatic lateral drift,
  orbit or focus change is added.
- Shot number no longer alternates camera movement types. The wide, medium,
  close, detail and medium-close sequence is only a suggestion for NEW keyframe
  framing. The approved image remains authoritative for the actual opening crop.
- For a tight demonstration that must stay framed, the existing last-frame
  control can anchor the ending to the same approved composition. This is an
  actual supplied image, not a text-only promise of camera restraint.

V1 allowed a nominally small push-in without checking the opening composition.
The V10 qualification clip enlarged the tissue detail by roughly 19% according
to sampled feature matching and progressively lost edge visibility. V2 removes
that assumption. Assessment is advisory grounding, not segmentation proof;
requested motion limits are still generative instructions. Check the rendered
clip for cropping, drift and feature visibility before selecting or exporting it.

Recognized legacy camera clauses are removed from the H3 execution prompt;
exact quoted dialogue is protected during that removal. Structured action plans
are preferred over unstructured prose, and continuations receive only their own
time window.

Task prompt text and its hash remain in the existing immutable task/attempt
lineage. The policy requests motion; actual camera movement and product fidelity
still need visual review of the rendered clip. Existing exports are not rewritten.

## Explicit production camera controls

An approved production plan can carry `motion_plan.camera_intent`, independently
of scene prose: `behavior` is `locked`, `tracking_backward`, or `push_in`;
`allow_reframe` is a boolean and defaults to false. Unknown behaviors and extra
fields are rejected. This selects one behavior per shot. Existing hard camera
locks and split-screen restrictions take precedence. Without explicit reframing,
the V2 margin and 2% push-in limits still apply. Intentional product-detail
endpoints can approve reframing; the supplied endpoint must still be reviewed.
The T-shirt case uses matched backward tracking, a locked pivot, a locked
sunglasses action, and an intentional detail push-in. Continuations inherit the
predecessor's admitted decoded final image. Their frame-approval check follows
the upstream qualified opening instead of demanding an independent first image.
Missing upstream anchors still block generation. Human talent is explicitly
bound with a `Person` role and is excluded from mascot palette instructions.

## Shared shot structure and model-independent cases

The semantic camera policy is shared by H3 and other video workflow prompts.
`planning/shot_structure.py` validates an optional `motion_plan.shot_structure`:
`stage`, `framing`, `angle`, `subject_motion`, and `keep_visible` entity IDs.
Manipulation locks the camera to keep grip, opening, garment and support legible;
a compound prose move cannot override this. New image stages receive the
requested angle/framing. An approved source image retains its actual opening.
H3 adds its provider field syntax after this shared decision; other workflows
receive the same camera instruction through the existing plain prompt path.

Timed grip, extraction, placement and release reuse the existing scene contract
and event dependencies. Phase conditions use an event-scoped check, for example
`{"id":"grip","scope":"event","event":"extract","claim":"The hand maintains contact while carrying the item."}`.
The event supplies the time window. Evidence outside that window cannot satisfy
or contradict the check; missing phase samples hold review. Sequence checks are
reserved for invariants that remain true throughout the shot. This avoids
requiring a continuing grip after a planned release. These are general physical interactions, not shirt- or
model-specific rendering logic. A reference showing soft packaging does not
imply a rigid box, lid, tag or extra actor. Required reference key/role pairs are
checked both in readiness and before preparing jobs; a reference must match the
exact selected asset and normalized role. Explicit neutral prop roles remain
neutral. Missing references are not silently substituted.

Version-3 production cases contain seconds and semantic reference/control roles.
Model graphs, native frame grids and sampler choices live in separate deployment
profiles. Applying a case uses the native storyboard APIs, rescales actions and
events to workflow timing, invalidates approval and queues no generation.
The T-shirt adaptation is `workflows/t_shirt.pipeline.json`; the previous
four-shot case remains `workflows/t_shirt.v2.pipeline.json`.

## Sources

- [MiniMax base prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md)
- [MiniMax reference prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)

These define the field vocabulary, reference alignment and camera type,
amplitude and speed. This implementation extends the existing application
compiler and sampler integration; it does not install another promptor service.

## Workbook-driven action timing

The optional timed form in the existing **Action** cell is one line per phase:

```
[0-0.5s] The hand establishes a grip on the cup.
[0.5-1.6s] It lifts the cup briskly off its support.
[1.6-3s] It places the cup back and releases the grip.
```

Times are seconds relative to the shot, independent of the video model and frame
rate. A timed list must cover the authored shot duration without overlaps or
gaps; describe intended pauses explicitly. Invalid timing stops planning. Legacy
free prose retains its previous interpretation. The original workbook is retained
in the project; timed lines are read before translation or motion summarization.

Follow-the-sheet planning preserves every interval and translates each action
individually. The existing production planner derives the opening still, scene
contract and shared shot structure, with a bounded schema-correction retry.
The shared camera compiler locks manipulation shots to retain contact and support;
locomotion tracks at subject pace while preserving the supplied framing. Explicit
preservation locks still take precedence. Neither faster subject movement nor
camera choice requires a provider-specific prompt or a per-product case override.
Native frame constraints remain in the workflow adapter, and the timeline retains
the workbook's editorial ranges. A planned 30 seconds is not evidence that a
finished export exists: verify the final export's frames and playback separately.

The current combined street/unpacking revision uses
`SAN PHAM AI/kich_ban/TShirt_4Shot_JoyMedia.xlsx` as its source, despite the
historical filename: eight scenes, 27 timed phases, 30 seconds. The previous
31-second JSON case is retained as an earlier recipe; it does not override an
imported workbook. Timed scene events and their causal order are serialized
from the authored phases, rather than independently inferred by the planner.

The References sheet optionally declares `Preservation mode` per picture:
`source_pixels` (the legacy default) or `reference_guided`. The latter is for
appearance conditioning, including deforming or occluded objects whose whole
photograph cannot be pasted into a different pose. It keeps the Product role
and model reference input, excludes that reference from pixel-pasting, and
requires visual review before a take is selected. It never claims exact artwork
pixels or lettering. Mixed scenes still enforce protection for every
`source_pixels` product. The workbook choice is frozen into run references and
approval signatures; changing it invalidates first-frame approval. No failed
strict run is silently converted to the other mode. A moving subject at the end,
as declared by shot structure, retains its action instead of receiving the
legacy two-second pose hold.

An optional **Opening reference / Ảnh mở cảnh** scene column names a selected
project reference (name or key). Planning binds that immutable image through the
existing first-frame API; unknown references stop planning. The normal workflow
then consumes it instead of redrawing a usable opening. This is separate from
informational illustration links. Blank uses the usual image-generation stage.
The generated scene still follows its timed Action cell and shared camera policy.
Source frames retain their actual crop; a requested wider view cannot manufacture
missing image content. Library upload deduplication only reuses library inputs,
so an identical prior project output cannot make a newly uploaded reference
unselectable.

**Ending reference / Ảnh kết cảnh** uses the same selected-reference binding for
`last_frame`, when supported by the video workflow. It anchors the ending pose
and composition without adding another physical subject. Both boundary images
remain authored controls in the workbook; the normal native pipeline stages
and validates them. Structured framing also applies to the early human-image
compilation path: it must not inject a default medium/wide shot into a detail
scene, or omit the product while describing its support.

## Review-driven camera, material and setting corrections

Before rerendering, map feedback from its immutable export frame ranges to scene
clips. Preserve the old export and comments. Revise timed actions and setting in
the workbook, then replan the affected scenes through the normal pipeline.

Locomotion uses persistent scene landmarks and continuous depth-dependent parallax,
not an independently sliding backdrop. A repeated first/last photograph describes
a loop or a return; leave the optional ending reference blank for open-ended travel.
Do not claim that prompt constraints alone prove background stability.

Both endpoint images must receive identical geometry before reaching a model. The
deployed H3 node internally stretches the first image but centre-crops the last.
The deployment graph now uses the same core ImageScale resize/crop on both, with
width/height supplied by the existing adapter. Absent endings stay disconnected.
This adapts the inspected upstream optional-I2V topology without copying custom
node code or changing the model-independent planner. Provenance is recorded in
`deploy/endpoint-workflow-reference.lock.json`.

Physical staging constrains deformation to local contact and the established
material; it does not infer elastic behavior from a hand gesture. The workbook
replaces edge pulling with pats and short surface smoothing where unchanged
printed dimensions matter. Environment references and scene settings, rather
than product-photo backgrounds, control the support surface across coverage.

For new keyframes, reference roles are explicit in the shared compiler. Product
references own object design and material; actor references own identity and
anatomy; environment references own support/location/light. For workflows that
declare multi-reference ordered chains, picture assignments follow present
role slots and bindings rather than the arbitrary project-reference list. An
actor photograph with incidental props is not an alternate product design.
Use clean role-specific references when competing photo content still dominates.
The opt-in deployment profile now reuses the existing FLUX.2 Klein reference
latent workflow instead of FLUX.1 Redux for multi-reference opening frames.

Identity screening keeps cast counting on every sampled frame. When an actor
enters/leaves, the three identity comparisons use interior quartiles of the
observed visible interval, avoiding partial entry/exit silhouettes. Persistent
actors retain first/middle/last coverage; short visible intervals use every
available view. Unknown comparisons remain blocking, as do witnessed identity
violations. The change is frozen by the existing admission implementation hash;
older held attempts are not retroactively passed.

When one workbook row combines extraction with a new contact action or a different
coverage scale, use separate timed rows and preserve their combined duration.
The editor makes the cut; each generated shot keeps one main interaction and the
shared policy chooses its camera behavior from structure. Opening references must
show the row's actual starting state. Keep approved opening views in References
and bind them through the workbook's opening/ending columns so a later import can
reproduce the same controls.

Product-only creative batches use the normal workbook importer and generation
pipeline. A gallery represents views of an identity, not additional actors or a
fixed number of shots. The writer can choose a supplied view per scene; native
reference binding retains that image through planning. Bulk image upload uses
Frappe UI's existing private-file uploader.

Motion references have an explicit purpose: camera, subject actions, or both.
Camera-only footage cannot supply subject action captions, and action-only footage
cannot override camera grammar. Source-hashed editorial corrections preserve the
original machine captions and record limitations; neither caption analysis nor
editorial annotation qualifies physical correctness. Previous intended end state
is passed into timed-sheet planning so persistent props do not silently reset.

Automatic versions retain their frozen backend execution profile during workbook
format application and native generation admission. The existing server-side execution-pin registry persists the selected profile
across environment rendering and later worker requests; explicit site configuration
keeps precedence. Scoped pins also cover immediate native operations. Neither is
exposed as a client model selector. Native runs still freeze immutable workflow steps.
Generated narrative-stage labels are semantic jobs (acquisition, demonstration,
inspection, final presentation), and are reviewed against the complete action
sequence before camera grammar is compiled.

Automatic timing reads the immutable workflow frame capacity. The generated script
must supply enough scenes, and the shared allocator caps each scene while retaining
the exact requested total. It never silently extends a workflow without a declared
continuation contract. Automatic screenplay stage labels remain advisory; the
normal production planner classifies the stage from the imported action rather
than treating an AI proposal as a customer's authored override.

When screening holds a frame, automatic generation stops. After explicit native
approval of the actual current artifact, a batch can resume without erasing the
screening findings. Stale approvals do not resume generation. Neither this
permission to animate nor a review export is a physical or release qualification.

Automatic batches freeze explicit reference preservation modes and write them into
the normal References sheet. Native workbook import therefore retains the same
choice; it must not silently revert a moving reference-guided product to strict
source-pixel compositing. Optional `execution_spec.reference_defaults` supplies
backend defaults only when the source has no explicit choice. Reference-guided
rendering still requires identity review and never asserts exact artwork proof.

Shared-setting preparation is a separate durable batch stage, reusing native
location generation and assignment for both image-guided and reference-only
workflows. The batch owns the subsequent visual handoff, so cancelling it cannot
launch new scene renders from a deferred setting callback. Failed location work
resumes from the persisted script/workbook. Existing image-only commercials can
state no cast explicitly in the generated template.

Structured output constrains JSON syntax but does not itself expose field
semantics to every configured language-model server. The shared planner request
now includes the schema and its descriptions in model context as well as in the
transport's decoding constraint, with a cache revision. A live diagnostic returned
an explicit request to supply the missing schema before this change and followed
the field instruction after it. Script review also checks explicit creative-brief
contradictions before production planning.

The delivery aspect also controls the active picture in the shared prompt compiler;
wide shot size must not be interpreted as a landscape inset in a portrait canvas.
A real reference-only test produced persistent black bands that the vision judge
incorrectly accepted. Native video admission now supplements its visual claim with
the installed FFmpeg `cropdetect` filter (upstream `FFmpeg/FFmpeg`, tag `n5.1.9`,
`libavfilter/vf_cropdetect.c`; LGPL-2.1-or-later). This invokes upstream detection,
without copying the detector or automatically cropping footage. Unrounded pixel
extents avoid alignment-rounding false findings. Persistent dark-border candidates
or unavailable detection hold acceptance for review; intentional dark sets can
resemble borders. A supported language-model verdict cannot override that hold.

Production planning receives each event's description and exact time window next
to its ID. A physical transition describes only that event's result, not a later
event or the whole shot's eventual ending. Authoritative workbook actions and
timing remain unchanged.

The shared stage classifier distinguishes a shot's narrative purpose from incidental
hand movement: presenting a held product is not automatically a grip demonstration.
Tracking still follows locomotion, but retains the source stage's declared camera
energy. Precision manipulation remains stable and reference preferences cannot
reframe a fixed opening without the required endpoints. Reference-only workflows
generate their opening and planned viewpoint progression, so an allowed reference
arc or reveal no longer falls back to a tiny push merely because no fixed opening
frame is supplied. This does not claim calibrated camera control: actual frames,
parallax, coverage and geometry remain subject to visual review.

Reference-only location conditioning retains the full setting image for every
shot size. The legacy fixed centre crop was intended for layout-bound image
guidance; it can remove a required support surface and is not used as a new
reference-only scene's setting. Shot structure owns the generated framing.
Opening/end-state planning also carries unchanged posture, support and object
placement across cuts. Automatic writing has no fixed five-second example to
bias every scene's timing, and text review flags reaction-only or repeated
presentation holds before workbook import.

Image analysis version 3 records product rigidity only with visible construction
evidence, distinguishing creased wrapping from a rigid container without assuming
an opening mechanism. This fixed a live case whose older caption called a flexible
pack a box, biasing scripts toward lids, closure and returning used contents.
Product observations are frozen into scene references and serialized into reference
roles without later database reinterpretation. They remain observations, not new
approved claims or physical qualification. Text review also rejects restoring used
consumables to unused stock as a narrative reset.

Creative invariants remain in model context during every repair, rather than being
lost when a compact repair request replaces the original drafting prompt. Pacing
findings receive the same quotation-backed cross-check as omission findings, but
must cite progress in the affected scene; motion elsewhere cannot excuse an idle
scene. A live planner check retained a looking-only finding and retracted a false
idle finding on material folding. Neither judgment qualifies rendered physics.
Generated sound cues use the native SFX/BGM labels so workbook import and H3
serialization do not silently discard unlabelled action sounds.

The native template also accepts optional `subject_motion` (locomotion,
manipulation, stationary), and the automatic script schema supplies it. This is
subject intent, not a camera prompt. It survives workbook import and overrides an
inferred hand-only classification when the actor actually travels while carrying.
The existing shared camera policy still derives tracking, and all output review
requirements remain independent of that classification.

Setting preparation no longer imposes an empty room or a blank lower-third floor.
That legacy layout instruction conflicted with authored floor props and encouraged
cluttered working surfaces. The existing empty-setting renderer now follows the
described location and preserves clear working areas and accessible openings;
actual generated furniture and access still require inspection before animation.

After an interrupted quality run, a batch may resume normal review finishing once
every current scene has an explicitly selected native take with matching generation
lineage and unchanged direction. Active runs, missing or unrelated takes, changed
direction and cancellation remain blocking. Failed attempts and their findings are
preserved; this handoff does not grant release qualification.
