# Reference preparation before storyboards

The automatic Creative Batch path now persists a script-derived preparation
plan before visual preparation starts. This extends the existing reference
registry and pose preparation rather than introducing another identity list.

1. Intake analyses original references. Registry identities distinguish a
   physical character from an illustration printed on the advertised product.
2. The Director writes the complete script. Each scene declares cast, products,
   opening support, timed actions, product viewpoint and grounded environment
   objects. An object's source quote must occur in that scene's authored text.
   AI-only inventory annotations that cannot be grounded are removed and saved
   in `inventory_rejections`; they cannot add objects to the authored scene.
3. `reference_plan.build_reference_plan` groups requirements by canonical
   identity and setting. Unregistered cast/products are rejected. Environment
   plates have an empty physical cast; working props are listed separately
   from permanent furniture and supports.
   Only permanent inventory objects feed the shared environment renderer.
4. Product view preparation tries H3 camera-transition clips unless an explicit
   image workflow is configured. Character preparation plans the finite required
   opening states, reuses qualified views, then tries H3 clips with the existing
   qualified image fallback. Flux remains the configured environment workflow.
5. Clips are retained as private project-attached preparation files. Exact
   decoded frame indices supply candidate PNGs. Original identity, required
   pose/view, support and physical plausibility checks govern promotion.
6. Qualified asset metadata retains the source clip, workflow hash, clip hash,
   frame hash and timestamp. Re-analysis preserves that lineage. The final
   preparation plan is copied into the storyboard source and frozen run context.
7. Existing scene binding, first-frame qualification, video review, editing,
   sound and export continue through the normal automatic delivery path.

The batch UI exposes the inventory and preparation clips. Clips are explicitly
labelled as preparation candidates, not finished footage. A prepared body pose
does not prove paper contact, acquisition, an observable action result, or a
physically valid shot: those remain scene and video checks.

## Product artwork constraint

H3 can propose a new camera angle but cannot establish hidden printing from a
single photograph. In strict source-pixel mode, even a machine-qualified AI view
is recorded as an inferred candidate with `source_locked` status. Original
photos and qualified source-preserving cutouts remain the actual artwork
authority. A genuinely required unsupported angle must be held rather than
claimed as achieved. See [reference-trait-validation.md](reference-trait-validation.md)
for the trial where both engines distorted fine print and the observer missed it.

## Evidence

Targeted checks cover canonical grouping, scene object grounding, exclusion of
undeclared actors, real FFmpeg frame sampling, qualified-frame lineage, strict
artwork fallback, pose preparation, metadata preservation, script validation,
location preparation, production planning and automatic delivery. Build and
live-run evidence are in
`/workspace/development/verification/preproduction-pipeline-20261029/`.

The fresh unattended run is CRB-00104 / PRJ-02727. Its terminal outcome must be
recorded separately; passing unit checks does not certify a final commercial.

440 targeted backend tests passed after the routing, extraction, inventory and
scene-binding recovery
repairs. The production frontend build, Ruff and diff checks passed. The first
live script attempt exposed overly coarse inventory-validation feedback and
spent its bounded repairs repeating unsupported furniture annotations. The
fix gives exact repair evidence and normalizes AI annotations from the actual
scene text instead of rewriting an otherwise valid story to retain them.

The live preparation panel passed browser inspection with two original
identities and no page errors or generation mutations. The registry regression
passed on PRJ-02726. PRJ-02724 now follows the new running child batch, so its
old completed-script browser fixture no longer applies during script creation.

The first native frame run, RUN-01370, failed without admitting an unprotected
frame. Its evidence exposed these additional issues:

- A product-free close-up inherited a pack from room-wide continuity notes.
  Explicit empty product rosters now constrain opening, boundaries and motion;
  continuity alone does not add a visible package. A positive authored package
  action contradicting an empty roster is rejected for repair.
- Product-lock instructions were included in product-free timed-shot prompts.
  These instructions now require an actual product binding. Reusable pose
  descriptions explicitly preserve the authored scene's props and contact.
- A measured-footprint rejection was classified as an unusable input rather
  than correctable staging. It now participates in bounded product restaging.
- A package-removal rewrite introduced facial cream, and another correctly
  negated a facial pack but triggered the presence detector. Standalone
  off-camera package world-state sentences are now omitted deterministically;
  other state text is preserved. Qualified negative package statements do not
  count as visible inventory. Ambiguous mixed sentences still cannot pass with
  an unbound visible package.

Native recovery replans legacy product bindings that contradict explicit empty
rosters, verifies their removal, and creates a new frame run. It preserves old
attempts and stops if its replan cannot repair the mapping. Automatic scene
rewrites also refresh product preparation, pose requirements and the stored
preparation plan. An old inventory cannot describe a new screenplay.

A live read-only replay after the fix returned a character-and-environment
close-up with a held tissue and no product key or package sentence. The actual
frame and final-video outcome must still be assessed separately; this is not a
successful unattended-film claim.

## H3 storyboard image route

`register_h3_storyboard_pipeline.execute` installs an opt-in pipeline from the
existing H3 reference-only workflow. It does not promote a global default.
Its image stage holds the authored opening for 39 preparation frames, selects
frame 36 through ImageFromBatch and saves an ordinary Primary Image. The
separate final H3 stage performs the authored timed actions; a preparation hold
never substitutes for an action. The full preparation clip is retained as a
private Intermediate artifact, attached to the project and visible with the
other preparation clips, never as a selectable take. Frozen workflow/snapshot
lineage and a clip SHA-256 identify the selected frame.

The registered local route is PIPE-00073: WF-02702 storyboard images, WF-02695
animation, with independent WF-02656 empty environments. Its product default
remains source_pixels. Batch requests honor the project's trusted backend
execution pin; client RPCs do not select internal recipes. This preserves the
application's administrator-only pipeline configuration boundary.

The live isolated H3 trial followed a tight paws-and-plain-tissue composition
more closely than the repeated full-body Flux results. Its clip and six samples
remain candidates, not admitted film footage. This supports testing the route,
not a general claim that all H3 output is physically or commercially correct.

Additional integration repairs normalize a copied revision screenplay back to
canonical identities before writer validation; stored pose/view bindings stay
untouched. Off-camera package continuity no longer counts as visible inventory.
Native geometry review now derives container counts from constrained object-form
observations, keeps unknown form unverified, uses a schema for reference-fit
decisions, and defines smooth matte surfaces separately from visible fur/pile.
The original source bytes and appearance metadata are unchanged. Admission hashes
now include the trait/lineage implementation dependencies; changed judges require
new run evidence rather than silently reusing old reports.

622 targeted backend test executions passed before the clean H3-route test.
The historical CRB-00104 run is diagnostic evidence and does not establish a
successful automatic final export.

CRB-00105 / PRJ-02728 exercised the H3 image route. Its first opening
incorrectly invented a retail box; the geometry gate rejected it. The compact
H3 prompt now carries only bound subjects and the authored opening, rather than
image-engine boilerplate about an advertised product in every shot. The retry
encountered a remote GPU-sharing memory stall. The preparation-only profile now
uses 512x896 portrait, 896x512 landscape or 640x640 square with 39 frames; final
animation settings are unchanged. The cancelled diagnostic is not a final export.
29 focused H3/bridge tests passed after this resource-profile adjustment.

The clean reduced-memory run also exposed a camera-variety conflict: a writer
requested the original product photograph, then the variety pass introduced a
move. Explicit original-photo hero placeholders with a static camera now become
the existing literal product hold. Camera variety cannot change that source
presentation; authored camera travel and real actions remain executable.
177 creative and prompt-scope tests passed, including source-hold recognition
and preservation of explicitly authored movement.

The reduced-memory route produced a 512x896, 39-frame preparation clip in
97.66 seconds and retained its sampled opening plus clip hash. The first still
visibly preserved the original smooth seated mascot and loose tissue on the
rug. Admission supported every concrete observation; its generic geometry
certification caveat remained. A later broad continuity description incorrectly
called the upright seated torso standing. Conflicting broad pose labels now
receive a separate blind support observation based on pelvis contact and foot
orientation. Missing/unclear evidence remains held, and actual standing still
fails a seated opening. A live recheck returned no physical findings; 72
physical-admission/automatic-delivery tests passed. This does not approve a take.
The next sampled opening still showed full-body coverage instead of the authored
close insert; the framing gate rejected it. Automatic recovery remains under test.

Two further live findings were repaired before continuing: exhausted close-insert
framing errors can now reach bounded scene restaging, with explicit instructions
to preserve real actions and change both structured framing and camera prose.
An earlier camera-variety audit can also identify and undo its own added move
on an explicitly requested original-photo hero; real authored movement remains.
A retry drew a cartoon on the tissue. Shared sheet-material screening now
explicitly excludes unauthored print/artwork at both opening and video stages,
without demanding a future extraction in the first frame. H3 receives this
constraint before composition prose. These repairs do not qualify failed images.

The stable studio trial exposed a deterministic script-validation defect before
GPU work: the duplicate-demo parser fell back to the earlier word tissue for
result clauses such as showing the crease and showing softness, rejecting
distinct fold/unfold and placement operations. Pronoun fallback now requires an
actual it/them object, and result-presentation clauses do not override a real
operation. Repeated standalone show/examine demonstrations still fail. 68
script-validation/camera tests passed after this fix.

Actor count and partial-foreground-human observations now require schema-bound
response fields. Earlier live checks returned an unverified-people gap on a
visibly actor-only frame; malformed keys must remain held, but the observer
should receive an exact response contract. Existing cropped-human and duplicate-
actor checks passed with the constrained calls.

Inspection of actual studio background files exposed unconditional furnished-room
and sofa instructions in the environment helper. These defaults are removed.
A separate schema-bound setting comparison now rejects a furnished room used
for a plain studio or neutral source-photo setting, even if it has open floor.
Foreground-negative clauses are stripped before place keying, preserving the
neutral setting instead of falling back to an interior. The H3 hold recipe now
declares free composition, so it receives the complete setting identity rather
than a legacy center crop. The new immutable route is WF-02702 / PIPE-00073.
The historical wrong-environment run CRB-00108 is cancelled, with its records
retained. 29 location checks and 71 script/camera/H3 checks passed. Generic idle
source-view product endings also normalize into the existing literal source
hold; their camera remains locked rather than acquiring a variety move.

A live revised environment render removed the sofas/table and produced clear
grey floor. The machine setting check passed, but visual inspection found
unrequested wall art. The remaining positive wall-art instruction is removed;
that diagnostic stays machine-qualified only, not visually approved.

Native source-hold recognition now also accepts an explicitly stationary
product named by its brand, when its structured subject state is stationary.
It rejects camera-only statements, additional transformation clauses and actor
scenes. This closes the gap between a correct static screenplay and the literal
canonical action used by the source renderer. 18 scope/camera checks passed.

Live material review exposed confirmation bias: direct constrained questions
called a visibly illustrated sheet unprinted, while free description correctly
reported its bear drawing and stars. `sheet_observation` now describes the image
first, then extracts sheet marks from that text with the same frozen vision
endpoint, requiring an exact supporting quote. Both passes and their results
are retained in admission evidence. Live printed/blank examples were correctly
distinguished. Up to five chronological samples receive this extra check;
unclear/missing observations remain held. This does not certify unsampled frames.

Absolute height is not inferred from a fictional character crop. Scale screening
requires a source Product/Person anchor or authored physical dimensions; support,
intersection, original proportions and topology retain their separate checks.
The generic geometry-qualification caveat remains, including for automatic
review previews. Source-product scale screening is unchanged. The prior
mascot-larger-than-paper rejection was not a measured contradiction.
52 admission/material/automatic-delivery tests and 23 physical-audit method
checks passed after these changes. No failed image was manually approved.
