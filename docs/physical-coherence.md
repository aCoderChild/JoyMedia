# Physical coherence in generated scenes

The application separates creative intent, scene relationships, workflow execution,
and visual evidence. A nicer-looking image is not evidence that the action makes
physical sense. No prompt or sampled vision verdict guarantees every video frame.

## Strategies examined

| Source | Useful strategy | Application here |
| --- | --- | --- |
| [Runway image-to-video guide](https://help.runwayml.com/hc/en-us/articles/48324313115155-Image-to-Video-Prompting-Guide) | Clean starting images; clear motion; sequential actions; remove conflicting implied motion | Review opening geometry before spending video inference; clip events to continuation windows |
| [Google video guide](https://ai.google.dev/gemini-api/docs/veo) | Reference images and first/last-frame controls constrain composition | Keep approved starting frames and immutable references; route supported controls through workflow capabilities |
| [PhyGenBench repository](https://github.com/PhyGenBench/PhyGenBench) | Separate phenomenon detection, event-order verification, and overall naturalness | Independent relational and event-order questions, with uncertainty requiring review |
| [VideoPhy-2 paper and project](https://videophy2.github.io/) | Action adherence and physical plausibility are distinct evaluation targets | Decode/job success and an action match do not certify physical quality |
| [VACE repository](https://github.com/ali-vilab/VACE) | Reference-conditioned and region/video-conditioned editing | Use a registered, validated editing workflow when its capabilities and weights exist; never fabricate support from repository presence |
| [VLIPP paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Yang_VLIPP_Towards_Physically_Plausible_Video_Generation_with_Vision_and_Language_ICCV_2025_paper.pdf) | Explicit visual and language physical priors | Motivate source/contact constraints and authored motion guidance; no dependency or backend integration is claimed |

These are engineering adaptations, not reproductions of the published benchmark
scores or new physics-model training. Fine branding still needs source-art
preservation or exact-take review. A local model is never silently replaced with a
commercial API. Additional workflow controls require live schema validation.

## Shared contract

`services/planning/scene_contract.py` is a pure, bounded contract independent of
Frappe, vendors, workflow node IDs, products and species. It lives inside
`Shot.motion_plan_json.scene_contract`, and therefore travels through existing
approved-plan signatures, frozen run snapshots, retries and workflow compilation.

Version 1 declares up to 16 entities, 16 relationships and 8 timed events. It
supports part ownership (`attached_to`), material origin (`flows_from`), contact,
and support. All relationship endpoints must be declared. Parts cannot have two
owners or cyclic ownership. Events require finite intervals within the shot;
every declared cause must finish before its effect begins. Invalid explicit
contracts fail at normalization, scene save and compilation.

The same contract supplies positive render guidance and bounded review questions.
Relationships remain in continuation prompts, while earlier events are not replayed.
Duration normalization rescales contract events alongside ordinary motion actions.
The contract is authored intent, never a statement that the output passed.

New creative and production planner instructions ask for these constraints.
Sheet-following translation also receives physical staging rules while preserving
its faithful-rewrite checks. Existing sheet plans are not silently rewritten into
invented entity graphs. An authored contract can be supplied through the normal
owner-scoped `update_project_shot` endpoint alongside motion and image direction;
it invalidates storyboard approval and cannot change while generation is active.

## Review and repair

Use a valid opening pose. Name the owner, material source, contact and effect.
Keep one principal interaction per generated shot. Author graphics, labels and cuts
in the edit instead of asking a continuous physical action to turn into a diagram.
When a source frame has an extra object or impossible leak, redraw it before
animating. When a generated action is wrong, simplify the interaction or use an
installed control/editing workflow; changing seeds alone is not a causal repair.

Contract failures and ambiguous answers become Needs Review without automatic
GPU retries. Missing media is Not Checked. Boolean approvals cannot be supplied
as numeric values, and character counts cannot be booleans or negative numbers.
Late reviews compare their exact media/direction snapshot under a short DB lock
before writing status, so a replacement take or first-frame approval wins.
Review samples include the clip's end; a sampled pass remains limited evidence.
The existing source-art repair and release approvals remain independent controls.

## Reproduction

`frontend/tests/live-scene-contract.spec.js` accepts external scenario JSON with
`project` and `cases` (`shot`, storyboard `index`, `duration`). No scenario identity
or model family is embedded in the test runner. It requires explicit live-render
opt-in, an authenticated test session file and an isolated test project.

Run `JOYMEDIA_SCENE_PHASE=frames` first, inspect the downloaded exact images, and
write their SHA256 hashes to `reviewed-frames.json` keyed by shot ID. Then run
`JOYMEDIA_SCENE_PHASE=render`. The runner validates those bytes, approves through
the real UI, clicks Redo, downloads the newly selected output and fully decodes it.
Use `JOYMEDIA_LIVE_RENDER=1`, `JOYMEDIA_SCENE_CASES=/absolute/cases.json`, and
`JOYMEDIA_TEST_SESSION=/private/session.json` for both phases. Authentication
material belongs outside source control.

Detailed local evidence is in `/workspace/development/verification/physical-coherence/`.
The broader existing concurrent queue, cancellation and export stress evidence is
in `/workspace/development/verification/live-render-stress/`.

## Additional boundaries verified

An explicit motion plan supplied together with a new image direction remains
explicit, even if its JSON content is unchanged. An ordinary direction edit still
clears old derived motion. The API returns the effective saved plan so callers can
verify the actual state rather than assume their input survived validation.

Body-part phrasing preserves existing possessives and modifiers. In a roster with
several identities, ambiguous limbs are not assigned to the first reference actor;
the authored relationships must identify the owner. Sound-effect fallback is
silence rather than a product-category-specific prop noise.

Finishing graphics are read from the matching original storyboard row, not only
from animation prose. The original request is included in the approval signature.
Thus a motion rewrite can remove the instruction to turn the scene into a graphic
without losing the counted insert in the composed footage. Legacy plans without
an imported source retain their explicit prompt-based inserts.

Remote preflight runs before the global run number is allocated, avoiding a
cross-project series lock during external model/schema checks. Whole-project
starts reuse their completed preflight. The real admission probe recorded eight
independent locking reads during a 32-second UI request, each below 1.3 ms.

Audio clips can open their inspector in timeline edit mode. The live test verifies
reusing a music asset, fitting it to the picture duration, changing volume, and
exporting the mixed result. Ordinary CI still skips all live-render phases.

## Temporal evidence implementation

Contract-driven takes now use the independent VideoPhy/VBench-inspired temporal
review module documented in `upstream-consistency-tools.md`. Legacy non-contract
checks remain supported. The UI offers **Check action & physical logic** and
**Review findings** on a selected take; the latter displays evidence and sample
times without exposing workflow nodes or raw service payloads.

Review requests are owner-scoped and bound to the take actually shown in the
browser. Evidence reads also verify the exact take, current direction and video
content hash. Structured model output is validated after decoding, not trusted
because it is syntactically valid JSON. The network review budget is bounded;
unreviewed claims never become implicit passes. Existing exact-take human brand
approval remains separate.

Live reproduction accepts the same external cases/session files as the render
harness. `frontend/tests/live-temporal-review.spec.js` requires
`JOYMEDIA_LIVE_REVIEW=1`, clicks the real review controls, checks private findings,
rejects stale/foreign requests and confirms no generation or take-selection
mutation. `scripts/review_video_cases.py` provides offline, owner-scoped candidate
review using the same implementation. It never selects or approves a candidate.

### Independent opening-state evidence

A real reversed-video control exposed a false positive from the vision judge.
The reviewer now also resolves the original conditioning artifact from the
**frozen generation-run snapshot**, following a bounded derived-asset lineage.
It does not compare an old take with the shot's current editable frame.

For an explicit conditioning image, blurred/downsampled global and local RGB
errors independently check the generated opening. Substantial changes request
review even when every VLM answer says supported. The tolerances are recorded in
the report; they are image-condition heuristics, not physical probabilities or
validated fine-brand metrics. Aspect-ratio disagreement remains uncertain.
Text-only workflows without a frozen opening image skip this comparison.

Negative-control manifests can declare an expected verdict. The offline runner
preserves evidence and exits with an error on any mismatch, so a false-positive
control cannot silently count as a passing test. The initial false-positive
report and corrected result are retained in the live verification folder.

## Guided controls and failure-specific correction

The five Shera review failures expose separate responsibilities. A furniture
intersection needs a geometrically staged opening; deliberate pouring needs a
correct driving performance; a human-shaped hand needs correct reference anatomy
and control geometry. Neither a source-label paste nor a successful video decode
repairs those three defects. The blank four-bar insert and overlapping closing
photo were compositor defects and now have deterministic replacements.

The optional `joymedia_workflows.guided_video` setting pins an immutable workflow.
The `generation.guided` service freezes `control_video`, `identity_reference` and
optional `control_mask` assets into ordinary Run/Task/Attempt records. A guide must
cover the scene, and a mask must match its guide's dimensions, frame count and rate.
Project access, library ownership, immutable content hashes, scene admission and
approved direction are checked before queuing. Candidate-only runs keep the
selected take and cannot trigger whole-film finishing. The studio's **Guide the
motion** dialog uploads these inputs and previews/downloads the separate result.

`workflow_adapters/graphs/wan_vace_guided.json` is a deployment template for native
ComfyUI VACE nodes, not a new default whole-film pipeline. It routes the mask to
VACE and also composites the original control frames outside the mask before
encoding. That outer composite is the mechanism that protects untouched regions;
VACE alone does not guarantee pixel preservation. Model-native frame padding is
expressed as `ceil_to_multiple` with an offset, followed by an exact output trim.

VACE reference/video/masked editing is documented in the official
[ICCV 2025 repository](https://github.com/ali-vilab/VACE) (Apache-2.0 for code and
Wan-based models). Commercial products similarly separate performance from
appearance: [Runway motion control](https://help.runwayml.com/hc/en-us/articles/50280558448147-Creating-with-Kling-3-0-Motion-Control)
and [Luma Modify](https://docs.lumalabs.ai/docs/modify-video). These are relevant
strategies, not evidence that this deployment achieves their quality.

`scripts/render_rigid_motion_guide.py` accepts operator-authored, bounded JSON
geometry and kinematic paths. The optional `previs` extra uses
[Pymunk](https://github.com/viblo/pymunk) (MIT) for rigid contact and gravity.
It writes the control clip and actual body trajectories. Circle particles are a
rough material-motion proxy, **not** a fluid/absorption simulation. This tool is
local authoring infrastructure, not an automatic physically correct scene planner.

Optional opening/sequence checks in `motion_plan.scene_contract.checks` distinguish
static staging from motion requirements. Opening checks feed the image prompt and
first-frame review, and temporal review evaluates them only at frame zero.
Sequence checks can distinguish actual morphology or accidental contact from
merely having an attached limb or a glass that tilts. These are sampled judgments,
not guarantees; a machine-positive result never supplies brand approval.

The closing compositor uses aspect-aware disjoint cells, preserves relative cast
sizes, uses source aspect ratios and avoids photo panels covering another subject.
It always uses a clean white card so transparent references cannot expose an
unrelated generated room. Prepared alpha references also remove photographic
background rectangles. `deploy/run-foreground-matting.py` is a separate optional
[BiRefNet](https://github.com/ZhengPeng7/BiRefNet) (MIT) driver: it infers only alpha,
asserts unchanged source RGB bytes, and records source/model/repository hashes.
Inspect pale edges before selecting its result; an inferred matte is not exact
silhouette ground truth. The client-requested paper-layer graphic is now a brief
full-frame macro illustration with countable textured sheets, rather than form-like
bars over the actor.

The real trials and rejected outputs are in
`/workspace/development/verification/logic-controls-live/`. The compact VACE model
trial is not a commercial-quality acceptance result: inspect its candidate footage
and manual verdicts. No new scene in these fixtures has brand/release approval.

Masked editing must remove the unwanted source pixels **before** model
conditioning. The VACE graph replaces the editable region with neutral gray
(128), following upstream `InpaintingVideoAnnotator.apply_plain_mask`. Passing the
unmodified region supplies the very anatomy being replaced as a control signal.
The final composite uses a second decode of the original video/mask at source
resolution, preventing a small repair from downsampling packaging. Reference
alpha is flattened on white and the image is padded to the native aspect ratio;
VACE's internal center crop must not cut off details in a square component crop.
A component reference (for example a gripper detail) can be more useful for a local
repair than a full figure containing several different limb types.

`scripts/prune_comfy_uploads.py` is a dry-run-by-default operator utility for stale,
source-backed upload copies. It restricts candidates to exact UUID filenames from
terminal attempts' declared file bindings for an explicit account, checks local
source files, and protects the live queue again before deletion. It does not
remove application outputs or weights. The current investigation only performed
an inventory; no remote upload cache was pruned.

### Support and relative scale at the first frame

The reference drawing branch must append the same `opening_instruction` as the ordinary image branch; returning its identity prompt early previously discarded authored starting-frame checks. Static `supported_by` and `attached_to` relations now reach the image stage independently of freeform checks. Future contact and material flow remain motion requirements.

A scene contract can optionally carry up to eight `proportions` rows with declared `subject`, `reference`, `axis` (`height`, `width`, `depth`) and finite ordered `min`/`max` ratios. These express authored physical dimensions at comparable camera depth; they are not detector measurements. Both direct and inverse duplicate pairs are rejected. The image prompt, frozen video prompt and independent review claims share these rows. Editing them changes the keyframe signature. Keep the target generic: reference image crop size is never object scale.

For seated interaction, name the seat supporting the pelvis and specify foreground occlusion by the work surface. A prompt such as “at a table” does not establish whether the actor sits on the table, on a chair, or on the floor. Review these relationships on the actual first frame before rendering motion. Prose constraints and vision-model judgments still do not guarantee correct geometry.

### Anatomy and contact references

Select the intended views of each identity explicitly. A pose photograph can contain
an incidental prop or gesture; role instructions do not guarantee that a generator
will ignore it. Do not combine conflicting pose variants merely to increase the
reference count. Compare body shape, limb attachment, paw/hand shape and relative
object scale with the approved view before admitting a new opening image. A close
crop cannot establish the proportions of a full figure that is outside the frame.

Repair an incorrect opening before running image-to-video again. For a local
contact demonstration, opening and ending references should agree on camera,
support, immobile objects, lighting and the acting limb. The ending must reveal the
physical consequence, not just a different pose over unchanged material. Bind both
images through the workbook's existing reference columns; the normal approved
plan, frozen inputs, workflow capabilities and review remain in force.

The native Klein profile supports an optional General composition reference using
the same reference-latent chain as its existing identity slots. Composition guidance
is additional conditioning, not an anatomy guarantee. A rejected image is never
promoted just because this workflow decoded it successfully.

Workflow delivery may declare `temporal_fit: "preserve_endpoints"` when native frame
grids exceed an authored duration. The compositor maps the complete source interval
to the requested frame count, including the actual final frame, with proportional
audio timing. The default remains trimming. This delivery choice prevents a
resolved end state from being silently cut off; it does not repair bad generated
motion or change the authored total duration.
