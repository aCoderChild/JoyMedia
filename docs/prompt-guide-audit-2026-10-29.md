# Prompt and reference audit — 29 October 2026

The Shera review export contains identity and material failures. The brown teddy
and subsequent turquoise toy are not the supplied cream mascot or a paper tissue.
Playable output and completed tasks do not establish visual acceptance.

## Causes and repairs

| Finding | Repair |
| --- | --- |
| Closing scene declares no cast but seats a bear in its continuity rule. Its actual first frame contains only the product and room; animation introduced the bear. | Empty cast governs every scene field. Normalize stale continuity in AI drafts; reject contradictory imported/executable direction before GPU submission. |
| Product caption describes a bear holding hearts without distinguishing printing from physical cast. | Explicitly retain depicted characters as flat package artwork. Product-only shots cannot authorize toys or humans. |
| Prepared-pose captions lose fixed appearance. | Store fixed identity separately from pose, background and removable props; freeze it into image/video references. |
| A generated pose could become its own identity authority. | Freeze original upload ID/hash through bounded source lineage. Compare identity with the original; compare pose anatomy with the selected pose. Changed reference bytes fail review. |
| Photographic-medium wording can turn the smooth 3D mascot into plush. | Preserve the actual source design and surface rather than requesting a photographed look. |
| Five authoring headings were passed directly to an H3 encoder that forwards raw text. | Serialize official base three-field or reference six-field prompts, with appropriate alignment and actual executable Picture/Subject bindings. |
| Paper can become a toy or packaging during handling. | Preserve thin flexible sheet identity through extraction, unfolding, holding, rubbing and placement; add a separate material invariant to video admission. Opening prompts do not require a future extraction. |
| Planning explicitly told the model generic “paper” meant the advertised product, conflating contents with its package. | Distinguish retail packaging, removable contents and printed artwork; only bind the package itself to its reference. |
| Diffusion unnecessarily regenerates a static product ending. | Route the application's literal static product action to the existing source-frame hold when the camera is locked. Real actions and performances remain motion tasks. |
| Anatomy observer can return a boolean without evidence. | Require schema-constrained visible evidence. Explicitly compare ear count, shape and attachment as well as limbs; normal occlusion is not a missing ear. |
| Physics rules require every table to have four legs. | Preserve referenced construction; still reject floating, disconnected or fused supports. |

The source ASTV-03707 and neutral pose ASTV-06332 were visually inspected. Their
appearance metadata records two small round ears with tan interiors, closed
upward-curving smiling eyes, cream smooth seamless body, tan paw pads and dark
claws. The user-provided pose already has ears. Image bytes and approval flags
were not changed. This annotation is not scene or release approval.

Fixed appearance survives intake refresh and pose preparation. New snapshots
freeze it rather than recaptioning a reference during execution. Historical
frozen runs are not rewritten. No breed or product name was hard-coded in the
implementation. The old five-layer helper remains for compatibility with
authoring callers, but is not the model wire format. Supplied speech is retained;
unsupported audio/video reference channels are not claimed.

## Live verification

Evidence: `/workspace/development/verification/prompt-audit-20261029`.

- The contradictory original closing prompt is rejected by the compiler.
- A corrected generative closing probe still invented a human and a turquoise
  bear-shaped toy. It is **Rejected**, unselected and retained for diagnosis.
  Admission recorded `cast_inventory` and `unrequested_human` violations in
  `rejected-probe-admission.json`. This is the bad probe shown during the session,
  not a repaired tissue-handling clip.
- Native source-frame hold PIPE-00047 / WF-02667 rendered
  `controlled-closing.mp4`: four seconds, 96 frames, 720×1280. Full FFmpeg decode
  passed. Comparison of all 96 actual frames with the source measured minimum
  SSIM 0.994801 and mean 0.994862, consistent with encoding differences. No toy
  or human was introduced. This checks preservation, not physical scale or a
  paper extraction action (`controlled-closing-verification.json`).
- Live source/pose comparison found no visible ear/limb distortion and supplied
  written evidence (`ears-and-limbs-live.json`). Empty-evidence responses were
  rejected rather than counted as passes.
- A fresh PRJ-02724 snapshot freezes ASTV-03707 and its original SHA-256 as the
  identity authority for ASTV-06332, including ears and eye design
  (`frozen-identity-snapshot.json`).
- A fresh native first-frame probe for SHOT-02975 now depicts a white paper
  sheet, two round ears and closed smiling eyes. It still places the mascot at
  the tabletop instead of on the authored rug. Visual inspection rejected it;
  the live geometry observer independently flagged unsupported weight. It was
  not selected or animated (`paper-frame-candidate.png`,
  `paper-frame-review.json`, provider `02144c26-d285-4fe7-92de-7dad0a7988be`).

Regressions cover H3 fields/binding order, supplied speech, empty-cast conflicts,
flat artwork, frozen original identity, paper handling versus packaging,
ear/limb evidence, static-hold eligibility and existing planning/review behavior.
Per-module logs are written by `scripts/run_tests.py` to `/tmp/joymedia-tests-*`.
The final targeted checks passed across 14 modules: 483 tests including all
creative-test categories. Ruff and `git diff --check` passed. Localhost returned
HTTP 200, the ComfyUI queue was idle and the scheduler remained enabled.

## Remaining qualification

The historical PRJ-02724 export and selected takes were not replaced by these
diagnostics. Its staging/scale findings remain held. Dynamic tissue-handling
shots still need new first frames/takes and decoded visual qualification; this
audit does not establish a corrected full film. Unseen package sides remain
unqualified. Sampled model observations cannot guarantee every frame or measured
physical correctness. The actor-action syntax guard is deliberately bounded;
semantic script review remains necessary. Failed/uncertain output stays held.

## Primary guides checked

- [MiniMax H3 base prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md)
- [MiniMax H3 reference prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)
- [Black Forest Labs multi-reference guidance](https://github.com/black-forest-labs/skills/blob/master/skills/flux-image-best-practices/rules/multi-reference-editing.md)
- [Black Forest Labs image-to-image guidance](https://github.com/black-forest-labs/skills/blob/master/skills/flux-image-best-practices/rules/i2i-prompting.md)

Installed ComfyUI `comfy/text_encoders/minimax.py` and
`comfy_extras/nodes_minimax_h3.py` were inspected for raw prompt forwarding and
actual picture ordering.
