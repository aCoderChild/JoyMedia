# Physical action contracts

A tool touching a material is not evidence that it performed the requested work.
The Shera extraction/wiping contact sheet and V13's 9–11 second insert expose this
failure: a plausible paw and paper shape can conceal an unconvincing fluid state
and an unreadable result. Existing broad action/contact judgments were insufficient.

## Inspected upstream implementations

Cloned checkouts are under `/workspace/development/research/physical-video/`.
Exact revisions and integration decisions are recorded in
`deploy/research/physical-video.json`.

- [VideoPhy / VideoPhy-2](https://github.com/Hritikbansal/videophy): semantic
  adherence, physical plausibility and rule grounding are distinct judgments.
  The MIT-licensed rule prompt from `VIDEOPHY2/template.py` is vendored with its
  license under `services/scene/vendor/`. The existing reviewer uses its physical
  rule question while keeping JoyMedia's grounded, uncertain/violated/supported
  response protocol. This does not run or claim scores from their trained rater.
- [PhyGenBench / PhyGenEval](https://github.com/OpenGVLab/PhyGenBench): inspected
  the multi-frame question generator and evaluator. Its focus on observable
  changes between initial, interaction and final frames informs the transition
  contract. No upstream code or dataset is copied from this repository.
- [PhysVid](https://github.com/5aurabhpathak/PhysVid): inspected local physics
  annotation, negative prompts, inference configuration and license. This is a
  Wan-based learned conditioning architecture, not an H3 plugin. Its
  CC-BY-NC-SA-4.0 code/checkpoints are not integrated into commercial execution.
  Research reference only; no claim of PhysVid inference or training gains.

## Workbook/brief to execution

The existing scene contract gains an optional `transitions` array. Each entry
references an existing event and describes observable `before`, `during`, `after`
and `forbidden` states. The planner derives these from the user's action;
there is no product, actor, model or wiping keyword router. Initial/result states must describe the same affected material or property, rather than merely the actor's pose. An unrelated static
scene does not receive an invented interaction. Existing contracts remain valid.

Timed workbook planning can infer only these consequences and shot structure;
the application preserves the authored event IDs, timing and action descriptions.
Invalid or invented event references fail schema validation. Timed schema repair preserves the source input once and sends back only inferred proposal fields; it does not duplicate the full rules and serialized event list into the context. A transition's
opening condition reaches first-frame planning only when its event starts at zero.
The shared physical prompt serializer sends contact and result constraints to
both generic video prompting and H3. Continuations retain current progress and
do not replay the initial state or demand a final state before its event ends.
Camera policy continues to prioritize readable contact for manipulation shots.

For the reported liquid-cleaning defect, the source Action cell should establish
surface contact, a visible stroke, a changing wet region along that stroke and
an exposed result. Keep a modest residual wet patch if total absorption is not
visible. A lifting tissue, an unchanged outlined pool, or an occluded result must
not be interpreted as successful cleaning. This guidance belongs in source
creative input; runtime code does not contain a Shera recipe.

## Evidence and admission

Sampling reserves distinct initial/contact/result frames at the declared event
anchors, before filling the bounded remaining budget. Interactions too short to
provide three distinct frames fail rather than manufacture evidence. Transition
review explicitly compares the same region and distinguishes occlusion from
material transfer. The existing structured vision request accepts phase frame IDs.
A supported result must cite the three ordered sampled anchors in both its frame
list and its phase mapping. Missing, duplicated, out-of-window, unsupported or
misordered evidence becomes uncertain. Violations dominate merged reports.
The original reports and raw model answers remain available; validation does not
repair a judge's answer into a pass.

The admission fingerprint includes these rules and the vendored upstream prompt.
Previously frozen runs cannot be retrospectively certified under the new policy.
Nothing automatically replaces an owner's selected take or approves a failed
render. The V13 diagnostic is partial evidence, not a full-scene approval. The live judge supported the sampled wipe; this disagrees with the owner's rejection. The new Physics feedback on frames 216–263 remains Open, and the existing release-feedback gate was checked against the actual reused take: release remains blocked. Re-exporting or copying that take does not clear the finding.

## Limits

This integration improves generation instructions and evidence requirements. It
is not a cloth/fluid simulation, a physical guarantee, or the full VideoPhy or
PhyGenBench benchmark. Sampled vision can miss a defect or mistake an appearance
for a state change; physical demonstrations still need visual review. A trained
motion-controlled model or simulation backend would need its own workflow,
reference capability checks and a real comparison before deployment.
