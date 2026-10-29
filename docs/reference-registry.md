# Reference registry and scene bindings

Each project subject has one canonical identity and original reference image.
Character poses and camera angles, and product views, are separate image versions
under that identity. Printed package characters are part of the product artwork;
they are not physical cast.

`services/scene/registry.py` builds the registry from selected references and their
recorded source lineage. It retains the original asset ID/hash, each concrete
view ID/hash, observed or qualified pose, angle and verification status. A supplied
photograph, a qualified reusable body pose and an AI-extrapolated product angle
remain distinct evidence categories. A neutral body reference does not prove a
later grasp or handling gesture. Unknown views remain unverified.

New run snapshots freeze `reference_registry`, per-scene `reference_bindings`,
`cast_ids` and `reference_requirements`. The latter retains the required opening
state, pose requirement and product view separately from the actual selected
reference. An actor/product view absent from the registry fails before execution;
the application cannot silently introduce an unregistered child or another mascot
as an executable reference. Image and video stages inherit the same frozen scene
bindings. H3 image-to-video uses the admitted first-frame pixels; independent
reference slots are used only when the selected workflow actually supports them.

The studio's character dialog and “View script & outputs” panel display the
originals, prepared views and scene map. They show required poses/product views
alongside the actual bindings. Caption refresh preserves pose qualifications,
product-angle provenance, negative verification flags and the empty-environment
contract; recaptioning must not turn an inferred angle into a supplied photo.

For a declared loose-consumable scene with no package, production planning checks
the opening image, starting state, ending state and motion direction for a carried-over
container. It attempts a bounded rewrite that retains the loose paper, actor pose,
support and action order. If the package remains, planning fails before execution.
An explicitly offscreen package or an instruction excluding packages does not add
visible inventory. This prevents the preceding shot's package from contradicting
the current scene's reference map through its state boundaries.

Generated room plates have an empty physical cast. Their prompts contain
architecture, furnishings, lighting and support-space requirements, without future
actor performances or character-reference styling. Physical people/characters in
the generated plate are rejected before it can become a storyboard reference.
Floor-only narratives use a floor-layout reference rather than a reused tabletop
plate. Missing or malformed observer decisions remain unverified.

This registry constrains declared inputs; it is not a guarantee that a generative
model cannot hallucinate a person or drift during video. Native cast, identity,
material and geometry screening still reject or hold such outputs. The child in
`a064baefd38329e0-2.png` was a rejected location candidate, never a registered cast
member or selected storyboard reference. The full fresh automatic export remains
under live verification in CRB-00103 / PRJ-02726.
