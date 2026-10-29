# Reference traits, plausibility and preparation engines

## Identity authority

A new pose or angle must retain the original input's observable identity, not
merely resemble its most recent generated predecessor. A generated starting
view can help motion or composition; it cannot redefine the subject.

`project.reference_lineage.original_reference` follows recorded source, cutout
and derived-version links to the original. Missing or cyclic lineage, malformed
metadata, excessive depth, missing image evidence and changed original bytes
fail before promotion. The original image's SHA-256 is verified.

Both H3 and Flux character preparation now pass that original separately from
the motion/still starting view. Original-reference checks cover identity, face,
material, colour, markings, accessories, visible ears and limb topology.
Observed pose, weight support and held props are separate checks. Missing
decision evidence, unknown material or unverified frontal eye design cannot
qualify a pose. A side/rear view need not expose hidden facial features, but a
changed visible eye design is still rejected. Ordinary perspective, pose change
and occlusion do not authorize stretched anatomy or invented visible traits.

Product generation likewise compares against the original, even when another
view supplies conditioning. Independent checks cover shared identity/print,
actual requested angle and physical plausibility, including material and
construction. Front, back and three-quarter views no longer receive an
unobserved default pass. Qualification metadata is versioned; incomplete older
AI-view qualifications are not current evidence. Hidden panels remain inferred.

If optional masking changes the bytes, the final candidate is checked again
before a Character/Product asset is created. A successful raw render is not
enough if its mask removes an ear, limb, artwork or package geometry. New
generated views record original identity version/hash independently of source
lineage; intake caption refresh preserves these fields. Existing mascot images
and their appearance metadata were not changed by this work.

These are machine screening gates. They reject observed changes and hold
uncertainty; they do not establish perfect perception or knowledge of unseen
surfaces. Strict product source-pixel mode continues to use supplied image
pixels, not generated artwork, regardless of an observer's preview verdict.

## H3 versus Flux: what the local evidence supports

Live settings on 29 October have no `joymedia_pose_workflow` override. Character
preparation therefore already tries H3 first and then Flux if H3 cannot qualify
the pose. An explicit image-workflow override remains supported. No global
engine switch or new model installation was made.

The six clips in `/workspace/development/pose-audit-2026-10-25/` retain much of
their own source mascot's recognizable appearance. They do not establish a
general pose success rate. End-frame inspection confirms a raised-paw result,
a purported foot-supported crouch that instead rests on its rump, and a side
reach that keeps its paw near the chest. Historical records also contain false
rejections. The audit uses its own flower-wearing identity; those images are
not references for the current project's different source. See
[pose-bridge-pipeline.md](pose-bridge-pipeline.md) for the historical results.

A new, unselected product trial used the same original ASTV-03698, target front
view, 640×384 output and seed 729104:

| Route | Frozen workflow | Output | Approximate render time |
| --- | --- | --- | --- |
| Flux Klein | WF-02656 | One still | 17 seconds |
| H3 image-to-video | WF-02681 | 73-frame camera transition; sampled at 2.1/2.5/2.8 seconds | 98 seconds |

This is a single-case diagnostic, not an equal-compute or statistical benchmark.
H3 visually retained more of the wrapper/top-panel presentation in this trial;
both routes corrupted fine print. The local vision observer marked identity,
view and physics as passing for both. This known false-positive evidence is
retained: it must not be described as exact printed-art verification. Neither
result was registered as selectable media or substituted into the project.

Evidence, exact graphs, media, hashes and observer flags are in
`/workspace/development/verification/reference-traits-20261029/`. In particular,
`engine-comparison.json` separates observer findings from promotion status.

The recommendation is H3-first for character pose transitions, with the same
original-reference gates on its fallback. H3 is a promising product-angle
candidate generator; this trial does not justify replacing factual product
photos with its inferred views. Flux remains useful for fast still composition
and environments. Both routes need source retention and plausibility checks.

Primary capability references:

- [MiniMax H3 model and task documentation](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/README.md)
- [MiniMax full-reference prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)
- [Black Forest Labs Klein model documentation](https://bfl.ai/models/flux-2-klein)

## Validation

212 targeted backend tests passed across original-reference lineage, pose
coverage, product views, metadata retention, registry bindings, pose-workflow
adapters, production planning and physical review. Ruff, format and diff checks
passed. No full repaired video, arbitrary-pose guarantee, or exact-brand
qualification is established by these tests or the product trial.
