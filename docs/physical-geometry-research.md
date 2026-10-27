# Physical geometry and action evidence

The local research checkouts are `../research/videophy` at
`01d366c979e4a82875852adbf427ccc036e7373a` and
`../research/PhysVidBenchCode` at `b1d20f121ed3ebe5d18337d884fdecfad065096b`.

[VideoPhy](https://github.com/Hritikbansal/videophy) (MIT) evaluates semantic
adherence and physical commonsense after a video exists. Its VideoCon-Physics
checkpoint and video inference stack would compete with the single GPU's render
queue, and its score does not specify how to repair a reference pose. It is a
possible offline comparison metric, not a pre-render admission check.

[PhysVidBench](https://github.com/ensanli/PhysVidBenchCode) describes a more
diagnostic sequence: caption the video from multiple physical perspectives,
then answer explicit yes/no questions using only those captions. Its public
repository uses AuroraCap plus Gemini and has no license file in the inspected
checkout. We adopted the evidence-first question pattern in the existing
reference/action validator rather than copying that code or adding two new
inference dependencies to production. The [paper](https://arxiv.org/abs/2507.15824)
reports stronger agreement with human physics judgments than direct VLM scores
on its benchmark; that does not establish accuracy on mascots or product ads.

The production path now carries `pose_and_support` from each analyzed character
image into the selectable reference view. If a scene chooses a seated view but
asks that actor to stand or travel, structural validation rejects the scene
before workbook planning or GPU rendering. The writer gets the precise
reference/action conflict for bounded repair. This rule applies to every
character identity and selected view; a supplied mobile view can be chosen
instead. Existing text and visual checks still inspect object acquisition,
support, contact, framing, and rendered motion. Automatic preview can carry
unresolved subjective visual notes, but no score is presented as proof of
physical correctness.

An accepted screenplay created before this rule must be regenerated to benefit
from it. A paper benchmark alone cannot correct geometry in a generated frame;
the first-frame and clip reviews must still show the actual pose, support,
product print, and material contact.

PRJ-02643 exposed a distinct first-frame failure: a rigid tissue-like dispenser
was fused to the mascot's head while the advertised pack stood separately on
the table. The existing product-support question covered the pack but not
other props attached to the actor. The image prompt now specifies separate
supports; first-frame review asks an explicit actor/prop support question, and
the existing first-frame review records that relation as a concrete finding.
This follows PhysVidBench's question-per-physical-relation pattern;
it does not assume VideoPhy scores can repair the image. The vision check is
still sampled evidence: on the known bad still it answered `true` while its
free-text reason misdescribed where the container was; on a later clean frame,
it also confused the small flower with a rigid crown. The new prop-attachment
question is therefore advisory (`Needs Review`), not an automatic redraw trigger.
Treat its verdict as a screening signal, not measured proof, and expose the
full preview for human choice.

Automatic batch delivery now assembles every usable shot into a provisional
whole-film preview before asking for per-shot changes. A take with unresolved
visual findings is marked `Needs Review` and remains visible in the timeline;
it is not silently promoted to a release-approved commercial. A shot with no
usable rendered take remains a real generation failure and cannot be inserted
into a complete film.

## PRJ-02670 first-frame regression (24 October 2026)

The seven Shera first frames showed a repeated table/mascot intersection. The
describe-then-compare audit did identify the support, table-edge and relative
size errors, but the batch classified geometry as a screenplay-only repair.
Earlier Shera versions PRJ-02642–PRJ-02645 contain individually passed frames,
mostly a standing mascot beside furniture or a product-only insert. Their
`Passed` labels do not prove that a new seated-at-table composition is safe.
The first-frame prompt omitted the stronger grounded-actor staging already used
for motion. A further task-preparation bug dropped `keyframe_retry_note` from
the frozen run snapshot, so even a redraw with an audit finding lost its
specific correction before reaching ComfyUI.

The image prompt now includes physical support and scale staging; clear
geometry defects receive two evidence-directed frame redraws before scene
restaging. Both task construction paths carry the frozen correction, and the
UI reads the shot's current findings so a rejected old picture is visibly
marked while an automatic repair is in progress. The single-GPU run remains
serial. This improves the odds of valid geometry but is not a physical
guarantee: the vision audit can miss errors, and exhausted retries still leave
a provisional preview for shot-level review rather than certifying a release.

## RefControl 4B evaluation and Shera real-image checks

The upstream [RefControl repository](https://github.com/thedeoxen/refcontrol)
was checked out at `1e9570b029ce38ed9bf02d9849cac6035b56b5b1` (Apache-2.0).
Its [Klein 4B depth LoRA and ComfyUI workflow](https://huggingface.co/thedeoxen/refcontrol-FLUX.2-klein-4B-reference-depth-lora)
were downloaded from revision `0ae1ef7f9acc4e55ec2237360943c3c3032d3583`.
The 92,426,784-byte LoRA has SHA-256
`65ec4c71fa7538b2201481928609a5836773f0dc06a4041b2d28abd05826c401`.
The upstream workflow applies depth conditioning before identity references on
both positive and negative branches. The adapted graph, execution spec, model
manifest, upstream graph and license live under `joymedia/workflow_adapters`.
The opt-in registration requires a **separate, validated layout image** as
`geometry_reference`. Depth extracted from an already impossible frame would
preserve its bad layout. It is not the production default and does not require
the previously rejected 9B model.

The local ComfyUI endpoint exposes the base and distilled Klein 4B models and
DepthAnythingV2Preprocessor, but did not expose the RefControl LoRA at inspection.
Its model-manager rejected installation of the pinned URL with HTTP 400
(`Invalid model install request is detected`). The GPU host SSH endpoint was
unavailable. Thus graph registration and validation were tested; **RefControl
inference was not tested or enabled**. Install the pinned 4B LoRA through an
authorized model-store path, verify its SHA-256 and the depth checkpoint, then
run a separate Shera A/B before promotion. Do not bypass the manager's model
allowlist or switch every still to the slower base model on this evidence.

Direct ComfyUI tests on PRJ-02670 shot 1 used the real mascot, product and room
references. The original first frame put the bear's body through the table.
Both base 4B and distilled 4B produced a floor-supported bear when given a
concise, explicit spatial composition, whereas the existing full image prompt
and its earlier retry still intersected the table. A compact retry retaining
the authored floor pose and separating actor and furniture produced a plausible
frame with distilled 4B. The describe-then-compare checker recognized the
original table support, but also mislabeled ordinary foreground occlusion as
an intersection on good frames. It now needs a second physical cue before an
automatic redraw for that particular claim. Product print still drifted in
these tests: geometry improvement is not proof of packaging fidelity.

The code-level regression covered prompt compilation, scene repair, physical
audit, frozen retry propagation and adapter graph/registration (76 tests passed
in the targeted modules).
Another live batch was rendering during inspection; no existing
project record or running job was changed. A clean references-to-export Shera
rerun after model installation remains necessary before calling this pipeline
reliable end to end.

## Geometry-aware product placement

`register_refcontrol_depth_pipeline.execute()` now registers a sibling
keyframe-to-video pipeline. It is deliberately not promoted. An operator may
map a proven base pipeline to it only after a ComfyUI inventory check, for
example:

```json
"joymedia_geometry_generation_pipelines": {
  "PIPE-BASE": "PIPE-GEOMETRY"
}
```

Routing is generic: a shot must contain both Product and Environment image
references. The approved Environment image is then supplied unchanged both as
the ordinary environment reference and as RefControl's required
`geometry_reference`; the pipeline never generates or guesses a layout image.
The sibling must retain every later video stage from the base pipeline and its
image stage must declare `depth_guided_reference` plus a required geometry
input. This is what makes the generated pack proposal follow the camera and
support plane in the actual room before source-art retention locks the supplied
pack pixels.

The current ComfyUI inventory has `DepthAnythingV2Preprocessor`, but not
`flux2_klein_4b_refcontrol_depth.safetensors`. The route is therefore
registered but not mapped or promoted. The validator reports that missing LoRA
before a task can be queued. Installing only a depth preprocessor is not enough.
After an authorized model-store installation and checksum verification, run a
real product-placement A/B in its supplied environment with the geometry mapping
enabled; verify a real first-frame artifact and its support contact before
promoting it for new projects. A single product image still cannot reveal a real unseen side panel:
the product-view contract continues to require a supplied angle for that.

## Product openings with measurable scale

`prepare_product_first_frame` now takes a four-corner support plane and an
anchor on that plane. OpenCV projects the pack width at the anchor's depth.
The caller can supply `scale_evidence` with measured `product_width_mm` and
`support_width_mm`; the width fraction is derived from those dimensions.
If only an estimated `width_fraction` is available, the frame remains a
candidate for review. The cutout retains its original aspect ratio and print;
the compositor adjusts room lighting within a limited range and adds a
table-clipped contact shadow. It records the source hashes, projected footprint,
contact points and pack/table baseline angle.

Selecting a product opening triggers a physical visual audit. The storyboard
shows its findings and requires approval; a changed cutout, background,
candidate, scene direction or product reference invalidates that approval.
Video preflight checks the same evidence before allocating GPU work. An
automatic batch may approve an explicit product opening only when measured
scale evidence and the physical audit both pass. Estimated scale requires a
person to inspect the image once, rather than discovering a bad overlay after
rendering a video.

On Shera `PRJ-02695`, Scene 5 uses this route with an estimated width fraction
of 0.29. Its cutout/table baseline differs by 4.78 degrees; the candidate is
selected but remains `Pending Review` because physical pack and table widths
were not supplied. There are no generated video assets for this project, so the
real-project validation covers the source images, first-frame audit and video
preflight gate, not motion or final-film naturalness.
