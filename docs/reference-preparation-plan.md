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
