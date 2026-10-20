# Identity and source artwork in marketing video

The application treats scene action, identity and printed artwork as separate
acceptance requirements. A model can perform the requested action while changing
a mascot's eyes or inventing package lettering. A successful inference, or a
vision model's action/count pass, cannot certify those details.

## Sources inspected and decisions

| Primary source | Applicable strategy | Implementation / deployment decision |
| --- | --- | --- |
| [Runway product-video API guidance](https://dev.runwayml.com/learn/generate-product-videos) and [reference media](https://docs.dev.runwayml.com/recipes/reference-media/) | Keep product references constant, approve stills before motion, use real images for printed text | Immutable identity sources in run snapshots; separate semantic identities from provider bindings. Candidate animation is not release approval. |
| [Runway reference-image workflow](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References) | Iterate composition and identity at the cheaper still-image stage; reuse approved references | Existing reviewed keyframe stage retained; full reference framing and transparency handling corrected. |
| [Adobe / Mocha tracking and corner pins](https://helpx.adobe.com/uk/after-effects/desktop/animate-in-after-effects/track-motion/tracking-stabilizing-motion-cs5.html) | Track a surface; apply original artwork using its four corners; separate foreground mattes | New provider-independent planar compositor and studio surface-selection editor. Exact-art repair does not require another generative video call. |
| [VACE repository](https://github.com/ali-vilab/VACE) and [input contract](https://github.com/ali-vilab/VACE/blob/main/UserGuide.md) | Reference images plus video and a mask allow local editing instead of rerendering the whole movie | Supported as a capability-declared graph strategy; no claim that its weights are deployed or a candidate edit preserves identity without inspection. |
| [MV-Adapter](https://github.com/huanngzh/MV-Adapter) | Candidate multi-view identity assets | Existing optional checkout remains isolated from Frappe. Views must be approved and grouped under one identity key; generated views are not new cast members. |
| [Hunyuan3D](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) | Persistent geometry for controlled rendering | Useful for product views or a subsequent rigging workflow. A generated mesh is not automatically an animation-ready mascot rig. Not made a mandatory dependency. |
| [BiRefNet](https://github.com/ZhengPeng7/BiRefNet) | Candidate foreground mattes from ordinary reference photographs | Optional preparation strategy; not a reason to invent an alpha mask or silently paste a photograph's background into an action shot. |
| [CoTracker license](https://github.com/facebookresearch/co-tracker#license) | Research tracking architecture and visibility estimation | Majority of repository is noncommercial. Not imported or deployed as the marketing application's default tracker. Runtime implementation uses headless OpenCV. |
| [InstantID usage conditions](https://github.com/instantX-research/InstantID#usage) | Human face identity conditioning | Human-face controls must not receive illustrated characters through a semantic alias. The repository also distinguishes code licensing from research-only checkpoints/dependencies. Not a generic mascot solution. |

These are architectural choices inferred from the documented control mechanisms,
not a head-to-head quality benchmark or a claim that every service was purchased
and tested. No customer reference images were sent to these commercial services.

## Contracts and boundaries

1. **Sources:** immutable Asset Versions and explicit canonical Identity Keys.
   `consistency.plan.identity_plan` groups multiple approved views as one subject,
   distinguishes reference guidance from source-art restoration, and fingerprints
   the source/control plan. It is frozen into each new run snapshot.
2. **Workflows:** ordinary versioned ComfyUI graphs with declared bindings,
   capabilities and limits. Model names and weights belong in graph/deployment
   records. Scheduling reads the selected workflow's frame capacity, including a
   separate continuation workflow's capacity; the original provider's 124-frame
   setting is no longer a global ceiling.
3. **Preparation:** editing source directions invalidates unchanged derived motion,
   end-state and handoff plans. Explicit scene continuity overrides the project
   default. Prompt assembly preserves scene duration and never invents product
   foley when no effects were specified. Reference boards contain the whole image, composite alpha on
   white, keep character/person semantics separate, version the rendering recipe,
   and write caches atomically. They do not crop away packaging edges or ears.
4. **Preservation:** planar labels/logos/artwork use tracked source surfaces.
   Characters that turn, bend or change pose need reference-conditioned animation,
   a masked edit with approved controls, or a persistent rig. The system does not
   pretend a flat photograph reconstructs hidden geometry.
5. **Review and release:** brand approval belongs to an exact take/reference set.
   Release validates the enabled video clips actually used by the timeline, blocks
   stale/unassigned footage and unresolved take comments, and rechecks under row
   locks before promotion. Review exports remain available. Release evidence is
   immutable on the exported Asset Version.

## Source-art restoration

The optional **Match scene lighting** control delegates illumination blending to
OpenCV's `seamlessClone` (`NORMAL_CLONE`) after the existing reference-anchored
homography and foreground mask. Default `blend_mode="source"` retains source
colors; `blend_mode="seamless"` can change them to match the receiving scene.
Neither mode establishes brand approval, and a planar repair covers only the
authored surface, not hidden sides or a deforming character. See the
[OpenCV implementation interface](https://docs.opencv.org/4.x/df/da0/group__photo__clone.html).

Operators can submit `select_result=false` to `queue_source_art_repair` to store
a repaired take without changing the selected take or starting finishing. The
request fingerprint includes this choice. This supports reviewing every repair
before an explicit take selection and avoids launching unrelated generation.

Install the optional `tracking` extra in the application worker environment:

```sh
pip install '.[tracking]'
bench --site <site> migrate
```

In the studio, choose **Restore original label / artwork** on a rendered scene.
Select an original reference and select four corners of the same flat surface in
the source and the first video frame, in the same perimeter order. Declare that
the surface stays unobstructed, or select an authored foreground-mask clip with
matching dimensions, frames and rate. White foreground-mask pixels hide the
replacement artwork. Mask selection is explicit; no missing mask is fabricated.

The owner API accepts Asset Version IDs, not filesystem paths:

```json
{
  "project_name": "PROJECT-ID",
  "shot_name": "SCENE-ID",
  "expected_take": "CURRENT-TAKE-ID",
  "planes": [{
    "artwork": "ORIGINAL-ARTWORK-VERSION",
    "source_quad": [[10,10],[200,10],[200,100],[10,100]],
    "target_quad": [[50,200],[250,210],[245,300],[45,290]],
    "tracking_quad": [[35,185],[265,195],[260,315],[30,305]]
  }]
}
```

Call `joymedia.services.consistency.repair.queue_source_art_repair`, then poll
`source_art_repair_status` with the returned job ID. The same status endpoint
accepts `cancel=true` in an authenticated POST. A finished job cannot be changed
to Cancelled by a late Stop request. CPU repairs use the long worker, independent
of the GPU finishing queue. Two repairs of the same take may compute concurrently;
only one may promote because the selected-take compare-and-swap is row locked.

The compositor re-estimates every frame against the original reference frame.
It checks unique feature matches, inlier ratio, spatial coverage, reprojection
error, convexity, scale and reflection. It rejects invalid controls, track loss,
corrupt/incompatible masks, cancellation and changed source files. Sources and
outputs have SHA-256 evidence; only a complete result is moved into place.
This confidence measures tracking geometry, not semantic identity or typography.

The app stores a new derived take with immutable preservation evidence. It never
overwrites the source asset. A newer take selected during computation prevents
promotion. Storage retries short rolled-back transactions after a conflict;
tracking and GPU inference are not repeated. Finishing is enqueued after commit,
so a downstream soundtrack error cannot misreport a committed repair as failed.
An automatic action judge cannot silently discard authored source-art repair.

Runtime limits bound frames, image dimensions, total decoded frame-pixels,
number of planes, encoder timeout and stored result size. A failed repair leaves
the current take in place. Missing OpenCV is an actionable preflight error.

The legacy static product-lock path now also refuses incomplete coverage. It
cannot silently hand back an unprotected model clip as a successful product lock.

## Selecting other providers

Workflow execution specifications can declare, for example:

```json
{
  "capabilities": ["reference_image", "multi_reference", "mask"],
  "limits": {"max_frames": 241}
}
```

The declarations describe controls, not quality guarantees. Graphs still need live
node/model validation and smoke rendering before promotion. Registering a newer
workflow does not replace the promoted pipeline or mutate a frozen run. Unknown
model families use the same generic adapter and binding contract.

Audio providers can be pinned by capability rather than a model-family name:

```json
{
  "joymedia_workflows": {"music": "WORKFLOW-VERSION", "effects": "WORKFLOW-VERSION", "narration": "WORKFLOW-VERSION"}
}
```

Legacy shipped workflow keys remain migration defaults. The inventory endpoint
`joymedia.services.runtime.inventory.workflow_inventory(project_name)` checks all
registered workflow revisions against the live server and returns actual failures.
A repository checkout, a loader node without model options, or a capability label
alone is not an executable model. The inspected server had 1,342 registered nodes
and 30 workflow revisions; 28 passed graph/node/model preflight. No automatic
promotion was inferred from that count.

A configured narration graph must produce Audio and declare the `speech`
capability; a music/foley graph is never assumed to speak the script. Exact text
is bound to `generation_prompt`, and an optional `voice` binding exposes voice
selection. Without this configured workflow the existing Edge adapter remains
available; its voice-name convention is isolated to that adapter. Narration cache
identity includes the provider/workflow version, voice, text and scene duration.

## Validation and current creative limit

The randomized tests cover 500 frame-capacity plans across different initial and
continuation workflows and 40 independent motion transforms. Real encoded-video
tests cover frame coverage, foreground occlusion, cancellation, concurrent jobs,
track loss, malformed regions, source overwrites and mirrored artwork. Owner API
tests reject stale takes and arbitrary paths. Release tests cover the actual
timeline sources, changed reference versions and unresolved review comments.

The real account repair restored the original package front across all 96 frames
of a moving product shot. Its largest per-frame median reprojection error was
approximately 0.95 pixels. The source and motion are application data; there is
no product name, shot number or model-family branch in the repair engine.

This does not certify the animated mascot, an unprocessed side of the package,
or an unobserved foreground interaction. Those remain separate review decisions.
The current film must not be called production-approved while they remain wrong.
Avoid another round of unconstrained random takes as the default repair strategy.

The corrected expression run also verifies that a revised direction no longer
contains the earlier “eyes widen” motion instruction or an unintended previous-
scene continuation. Its sampled frames retain dark eyes; that improvement is not
an automatic approval of every frame or every other scene. A failed face-surface
repair stopped on ambiguous tracking at frame 22 without promoting an output.

### Source artwork on an authored surface

Reference conditioning can still invent packaging, typography and printed
characters. For a fixed product view, prepare a transparent cutout whose RGB
pixels match the original photo. Keep the original asset and derive the cutout
from it; transparency must not repaint the artwork.

The motion plan accepts `artwork_placements`, alongside its scene contract:

```json
{
  "scene_contract": {
    "version": 1,
    "entities": [{"id": "product", "label": "the reference product"}]
  },
  "artwork_placements": [
    {"asset_version": "SOURCE_ASSET_VERSION", "entity": "product", "box": [0.1, 0.45, 0.25, 0.18]}
  ]
}
```

The box is `[x, y, width, height]` in image fractions. The existing compositor
fits the visible source artwork into that area without stretching it, aligns it
to the area's bottom, and supplies a contact shadow. It refuses unselected or
opaque artwork. The optional entity must exist in the scene contract. The image
prompt excludes that entity's structural instructions, because the compositor
supplies it after inference; otherwise the model may draw an additional product.
The final composited frame remains subject to the complete structural review.

Inspect the actual table, shelf, floor or other support in the generated frame
before approval. Normalized coordinates alone cannot establish physical contact,
perspective, depth or foreground occlusion. Position and scale are authored data,
not product-category defaults. A compatible source view is required; this mode
does not rotate a photographed object into an unseen view.

`generate_keyframes(..., draw_places=False, seed=<integer>)` can replay image
noise when correcting only artwork position. This preserves the existing model
input and gives a repeatable composition within a compatible runtime. The seed
is frozen on the new run; earlier images and videos are retained. Artwork
positions participate in the keyframe signature, so a changed placement requires
fresh approval. The default remains a new image seed per run.

The existing video product lock reapplies the saved source patch only when its
full frame coverage check succeeds. A cut, significant camera move, or lost
coverage rejects the output instead of silently accepting generative branding.
For moving surfaces or foreground occlusion, use tracked source-art restoration
with authored planes and occlusion masks. Neither method certifies animated
mascot identity, physical action, transparency/refraction, or unseen product
geometry. Review those dimensions separately.

Individual shot prompts must contain only that shot's action. Scene-specific
macro demonstrations and closing directions belong in their own shots, not in
whole-film global instructions. The generator holds the current shot at its end;
the editable timeline implements transitions and the next scene.

An unselected take can be repaired with `source_take` while `expected_take`
continues to guard the current selection. Both versions must belong to the same
scene output asset. The repaired result retains the actual source take and
provider attempt in its lineage. A rejected candidate need never become visible
as the current preview merely to prepare a repair.

An explicitly authored `tracking_mode: "fixed"` plane is available for locked
compositions and fixed screen artwork. It uses declared canvas coordinates;
it does **not** follow a generated object's motion. Its certificate says
`fixed_source_plane` and contains no measured tracking error. It cannot include
tracking controls and is never an automatic fallback after lost tracking.
Check support contact, perspective, camera stability and foreground occlusion
visually before selecting it. Moving objects require tracked planes or a new
render. Neither plane strategy reconstructs unseen surfaces.

## Automatic retention policy

`joymedia_reference_retention` is an operator setting, not another customer step.
New run snapshots freeze its recipe digest and immutable preparation workflow
revision. Earlier runs and exports retain their original behavior. The registered
`reference_retention` workflow uses ordinary semantic bindings (`scene`, `source`,
`recipe`); application services do not load model checkpoints or rewrite model
node IDs. Another provider must implement the same preparation evidence contract.

The installed adapter reuses the official MIT BiRefNet implementation for alpha
and the official Apache-2.0 GroundingDINO model through its documented Transformers
integration for open-set detection. Repository commits and model revisions are
in `deploy/reference-retention.lock.json`. `deploy/install-reference-retention.py`
requires a separate mounted volume with at least 64 GiB available and places
repositories, checkpoints, caches, temporary files and adapters under that root.
The Comfy service needs `JOYMEDIA_RETENTION_MANIFEST` set to the installed manifest.
The adapter runs upstream packages in an isolated process because their generic
`models`/`utils` modules conflict with ComfyUI's module names. It verifies its
adapter digest against the pinned manifest before accepting a request.

For ordinary product photographs, the image generator proposes staging only.
Preparation derives alpha without changing source RGB, detects the product,
rejects ambiguous/cropped/incompatible footprints and detected limb occlusion,
then replaces the proposed artwork with the original source. OpenCV Telea
inpainting reconstructs the receiving background inside the detected footprint
before compositing, so rejected generative packaging does not remain visible
through transparent corners. This reconstruction is **background synthesis**, not
proof of an unseen product surface, physical contact or correct lighting. The
matte and placement still have detector error limits; the cheap first-frame
review remains appropriate. Cropped, overlapping, multi-part or ambiguous source
views may require better reference photographs or a declared editing workflow.

Exact existing authored placements and deterministic source closing cards remain
supported. Locks now identify the immutable reference they protect. Video
assembly requires coverage for every frozen product reference and every video
frame. A missing lock, changed reference, incomplete preparation or lost video
coverage stops delivery; it cannot silently revert to unprotected generated art.
Preparation rejection is terminal input failure rather than a repeatedly polled
Running task or an automatic expensive video retry. The real provider job and
its processing diagnostics remain available for the administrator.

Prepared images and patches are cached privately under their input/recipe hash,
with output hashes and the actual Comfy prompt ID. Reuse validates cached bytes
and does not depend on the provider retaining history across restarts. Different
references, source bytes, source scene, workflow hash or model recipe create a
new preparation. No original Asset Version is overwritten.

### Moving identities

A paired-reference vision screening experiment accepted a known changed-eye
mascot as consistent. That judge is therefore **not** a production acceptance
mechanism. The qualification utility and observed results are retained for
retesting; a positive semantic score is never exact-identity proof.

Under the automatic policy, character/person scenes produce unselected candidate
takes. They do not replace an already selected take, patch its timeline or start
finishing automatically. A completed candidate is tracked as completed work even
when the scene has no earlier selected take. Existing take review/history is the
selection boundary. Fully deterministic source-image holds are exempt; merely
conditioning an animation on a reference, or declaring a rig capability, is not.
A future persistent rig or qualified identity control needs its own evidence
contract before this conservative boundary can be relaxed.

This automates source preparation and prevents silent promotion of unsupported
motion. It does not claim that arbitrary animation can preserve every feature
without review, or that detection proves four-legged furniture, ownership,
refraction, hidden geometry or temporal physical logic.

### Route static source shots before diffusion

The live video test invented a protruding tissue on a sealed package despite a
still-package direction. The generated attempt was rejected by coverage, retained
as evidence, and did not replace the working video. Repeating the same diffusion
request is not the policy for a shot that explicitly requires no subject motion.

A product-only plan may declare `camera_motion: "locked"` and a valid scene
contract with `motion: "stationary"` properties on every physical entity and no
physical events. Shared planning instructions describe these controls. Only those
positive facts select the configured source-frame presentation pipeline. Missing
facts, actors, events, or a moving camera cannot silently become a frozen shot.

The presentation pipeline reuses the configured image workflow, automatic source
preparation and the installed VideoHelperSuite encoder. Its ordinary versioned
Comfy graph repeats the prepared image at the requested frame rate and duration;
there is no neural model between the source frame and the encoded presentation.
The selected default video pipeline stays unchanged for moving scenes. No fake
H3 attempt is recorded: the source-hold workflow and actual Comfy prompt identify
the operation. The workflow is an operator-declared capability, not a product-name
or model-name branch. Rotating products with unseen sides and articulated
characters need another proven control strategy; this route does not invent it.

### Reproducing the deployed preparation

Run the installer in the existing GPU Python environment, pointing storage at
its large mounted volume (never the server root disk):

```sh
python deploy/install-reference-retention.py \
  --storage-root /var/lib/kubelet/joymedia-model-store \
  --comfyui /home/ubuntu/ComfyUI
```

Set `JOYMEDIA_RETENTION_MANIFEST` on the ComfyUI service to the printed manifest,
restart it when idle, and register the versioned preparation and presentation
workflows through the two `register_reference_retention` and
`register_source_frame_hold` patches. Enable site `joymedia_reference_retention`
with `enabled`, the preparation `workflow`, printed `recipe_sha256`, and optional
`source_hold_pipeline` / `source_hold_workflow` returned by registration. The
installer refuses the root filesystem; it does not silently enable app policy,
change existing Torch packages, or promote a new default generation pipeline.
New run snapshots freeze these choices; existing history keeps its old recipe.

Live qualification evidence is in `verification/automatic-retention` in the
workspace. RUN-00618 produced a five-second, 120-frame source presentation through
the real UI and ComfyUI. Exact source RGB is checked in preparation; delivery
H.264/YUV420 is lossy and is not bit-identical to the source photograph. A cached
preparation was replayed without network or provider history. Drinkware source
preparation succeeded; uncertain ceramic/cosmetic placement was rejected. These
are bounded checks, not proof of universal product, anatomy or physics accuracy.

### Physical placement is a separate acceptance requirement

A preserved label is not evidence that its object belongs on a table. In-room
product composition no longer falls back to an image-relative position. Explicit
placements require `support_surface` with a convex normalized `polygon` and the
`background_sha256` of the exact uncomposited frame. OpenCV checks visible lower
source contours against that region before pasting. An old region, missing
support, floating footprint or overhang is rejected. These are necessary 2D
checks, not proof of correct perspective, dimensions, shadows or occlusion.

Automatic detector placement remains a proposal. Product-bearing scenes under
the retention policy now stay unselected candidates even when a static source
hold preserves every brand feature. They cannot start finishing automatically.
Full-frame deterministic closing artwork remains a presentation card, separate
from physical scene certification. Existing selected videos are not silently
rewritten by this change. Scene history and explicit review select a candidate.

### Reference anatomy and stationary regions

Seating is fitted to the source anatomy; an actor is never lengthened merely to
reach the floor. Shared planning rules preserve topology and relative part
sizes, and permit a footrest or a different seat height where the brief allows.
`scene_contract.parts` accepts zero only as an explicit absent-part requirement.
For example, an established reference may forbid an elongated limb segment or a
vessel handle. This does not infer absence from occlusion; ordinary instance
counts remain positive. The prohibition is compiled into opening and sequence
checks, and actor identity plans explicitly require reference topology and
proportions.

For a locked-camera action, the existing source-plane repair API can preserve a
stationary region from an inspected source frame while allowing motion elsewhere.
A lower-body region may remain unchanged during an upper-body action if the beat
requires no lower-body movement. Fixed controls are explicit authored regions,
not automatically recognized anatomy or tracking evidence. Moving cameras,
foreground crossings and actions inside those regions require other controls;
source region preservation must never conceal a required action. Every repair
retains its source hashes, controls, output version and frame coverage.

The seated-proportions qualification also demonstrated that a locked-camera
prompt is not measured camera stability. A fixed rectangular body hold created
visible furniture seams; broader motion mattes exposed passive-region inventions
or interfered with coherent body animation. Those variants were retained as
superseded experiments. The selected result keeps the naturally compact native
pose and restores only passive props using measured background motion. Tracking
covered all 96 frames with maximum reprojection error below 0.27 pixels. The
lower-body crops were visually inspected across all frames; this is not an
automatic anatomy certificate. A 30-second V4 review export retains the correction
and all previous versions. Evidence: `verification/anatomy-20261018`.
