# Shera production and product-only automation: open issues

Status checked on 22 October 2026 against the live `joymedia.localhost` Frappe records,
the current application code, and the exported film. This is an issue register, not a
claim that a generated video has passed brand or release review. Earlier dated reports
describe their own versions; see [Shera workflow audit](shera-workflow-audit.md),
[physical action contracts](physical-action-contracts.md),
[Ref2VA integration](ref2va-integration.md), and
[camera policy](h3-camera-policy.md).

Later same-day automatic-delivery execution and updated findings are recorded in
[Automatic reference video](automatic-reference-video.md). The table below remains
the earlier snapshot; its unresolved quality findings are not closed by a preview export.

**Latest same-day result:** `CRB-00036` / `PRJ-02621` completed an automatic
seven-shot screenplay-to-ComfyUI preview, then a reviewed three-shot FL2VA
replacement and a final 30.000 s export `ASTV-05446`. The extracted-sheet
action and beige-room carry/ending defects visible in the first export were
repaired in the selected takes. This supersedes the table's old claim that no
source-reference batch has reached export. It does **not** close the moving
package-print, subjective music-listening, non-Shera aspect-ratio, multi-video
scale or release-review gaps. Native run IDs, failure evidence, code fixes,
tests and decoded contact sheets are in
[the PRJ-02593 automatic-pipeline audit](prj02593-pipeline-audit-2026-10-22.md).

## Current deliverables and evidence

| Item | Observed state | What it proves |
| --- | --- | --- |
| `PRJ-02593`, output `ASTV-05069` | Completed review export; root `PRJ-02501.current_edit = PRJ-02593`; MP4 is 30.000 s, 720×1280, 24 fps, with video and audio streams | A viewable Shera cut exists. This does not certify every moving frame, creative quality, or release eligibility. |
| `SHOT-02455` in that cut | Selected take `ASTV-05068` is a source-image Shera logo/package close-up | Exact printed artwork is used for this insert. It does not make Ref2VA's moving product appearances pixel-exact. |
| `PRJ-02590` | Source-only 30 s/9:16 test project with two product views and two mascot views; no workbook, setting image, or action-motion reference | Exercises the intended minimal-input path, but does not supply evidence for a complex physical demonstration. |
| `CRB-00014`, `CRB-00015`, `CRB-00017` | Rejected/cancelled exploratory drafts; no ComfyUI rendering from these batches | Real generated drafts contained idle shots, an unsupported anonymous hand, or an unanchored cleaning action. |
| `CRB-00018` / `PRJ-02595` | `Needs Attention`; bounded screenplay repair failed, no accepted script or final video | The product-and-mascot-images → script → ComfyUI → film path is not yet qualified end to end. |

The last targeted validation of the script code passed 25 tests, including rejection
of a preparatory-only shot, an anonymous human hand, and cleanup without an action
reference. These are contract tests. They do not demonstrate that the configured
writer can produce an acceptable screenplay. Code is on the
`refactor/production-maintainability` and `fix/production-pipeline-contracts`
branches; neither branch being pushed implies a release deployment or a reviewed
film.

## Issue register

Priority means production impact: **P0** blocks a trustworthy automated release;
**P1** blocks a reliable product-led result; **P2** is a maintainability or evidence
gap. “Guarded” means the system now rejects the known failure, not that it can
generate a successful replacement.

| ID | Priority / state | Problem and evidence | Required fix and acceptance |
| --- | --- | --- | --- |
| A01 | P0 · Open | The configured writer still spends a scene merely noticing, walking to, or reaching for the product. `CRB-00018` exhausted bounded repairs; `PRJ-02595` has no accepted script. | Introduce a compact action outline before full prose, with explicit actor, object, prerequisite, contact and changed state per beat. Reuse the existing timed-action, scene-contract and workbook pipeline. Prove on a new product-only Shera batch that every non-closing scene completes a distinct interaction and the full script is accepted without manual rewriting. |
| A02 | P0 · Guarded, generation unproven | The old drafts `CRB-00014/15` passed with idle/repeated beats. The new `creative.py` progress gate rejects those drafts, but the writer has not reliably repaired them. | Keep the gate; test a successful output, not only rejection. Measure action variety, repeated presentation holds, causal state handoffs and total pacing on the accepted 30 s screenplay and finished video. |
| A03 | P0 · Open | The full-screenplay repair loop repeatedly rewrites a defective premise and returns only an error; `CRB-00018` has no saved rejected screenplay. This obscures which attempted revision failed and why. | Persist bounded rejected drafts, exact validation findings, model/request identity and repair attempt number as private batch evidence without treating them as accepted scripts. Allow targeted scene repair or fresh outline selection. A retry must be diagnosable and must not reuse a cached invalid answer. |
| A04 | P0 · Guarded, live recheck needed | A real draft introduced an off-screen hand although the source-only roster had no person; it also invented dust-cleaning without action footage. The current validator blocks the tested English forms, and `CRB-00017` was cancelled before render. | Ground every visible actor and physical effect against selected identities, approved claims and action observations. Check the entire action/visual/continuity prose, not only a word match in Action. Run a fresh accepted batch to verify no unreferenced actor or unsupported effect reaches ComfyUI. |
| A05 | P0 · Open | Exact mascot proportions, paw connectivity, support and product print remain unproven across all moving shots. Earlier Shera reviews document distorted body/seat geometry, invented hands and altered package text. Ref2VA references are guidance, not exact-pixel preservation. | Use reviewed identity views and product art as explicit workflow inputs, inspect opening/contact/end and all brand-critical frames, and use the existing source-art/tracking or source-motion path where artwork must be exact. Reject uncertainty instead of auto-selecting the take. Qualify Ref2VA against original images in real jobs before making it the default route. |
| A06 | P0 · Open | The historical water-wipe was rejected by the owner despite an automated plausible rating. The current product-led cut avoids that event; this does not fix water/contact physics generally. | For any claimed demonstration, require source-approved action, start/contact/result evidence, uninterrupted support and material-state change. Keep the existing physical-transition and release-feedback gates. A test of the actual rendered action, not a prompt or sampled single frame, is required before release. |
| A07 | P1 · Open | `PRJ-02593` shot 5 now selects the Shera logo macro, but its `Shot.shot_name`, imported source scene and original Excel still describe disposing of the used sheet. The stored brand logline/mandatories still mention disposal and gradual water absorption. | Create a versioned storyboard/workbook matching the selected cut and update its shot label, action, VO/SFX, product claim and source snapshot through the normal edit/version workflow. Re-export with an accurate manifest; preserve the old workbook as historical provenance. A reviewer must be able to reproduce the edit from current project data. |
| A08 | P1 · Open | The minimal-input project has four images but only two identities; it has no environment or action-motion reference and its selected `keep_rule` fields are empty. The writer therefore invents rooms/actions, while source-product construction is not explicitly locked in these rows. | Let reference analysis distinguish immutable identity/product facts from optional creative choices. Offer image-role suggestions and safe default preservation constraints in the existing reference-selection contract. When motion evidence is absent, choose simple supported handling and exact-art detail; do not invent liquid, cleanup, deformation, a rigid package lid, or an unprovided actor. |
| A09 | P1 · Open | The current action-progress check uses English verb and effect regexes. It can miss a valid synonym such as “acquires,” misread passive set dressing as action, or miss another language. A relative-clause fix covers one observed false positive only. | Replace lexical acceptance with structured event fields and grounded actor/object/state links while retaining a cheap lexical precheck. Test English, Vietnamese, passive descriptions, synonyms and mixed narrative. The user input must not require model-specific or Shera-specific branches. |
| A10 | P1 · Evidence gap | Camera grammar from the DOCX and hoodie reference is present in project data and shared policy, but no per-shot audit of `PRJ-02593` establishes actual final movement, parallax, framing, action visibility, axis continuity or hook strength. A source-image push-in proves that insert only. | Produce a cut-level camera report from decoded video: shot boundaries, shot sizes, observed movement, crop/safe margins, action contact visibility, axis/match-action handoff and reference comparison. Review it with the owner; revise footage when the physical camera result fails. Keep camera behavior in structured shot policy, separate from action prose. |
| A11 | P1 · Evidence gap | The 30 s export has an audio stream and an authored music bed, but the owner's “dull music” comment has no documented listening sign-off for this cut. | Check actual BGM level, cue changes, dialogue masking, edit rhythm and ending resolve on the exported mix; replace or remix the bed using the existing music workflow/timeline. Approval concerns the heard result, not the presence of an audio stream. |
| A12 | P1 · Open | Product advertising emphasis improved in `PRJ-02593`, but exact Shera print is guaranteed only in source-art inserts. Moving scenes still need source-to-frame comparison; the source workbook has an old disposal beat rather than a product detail. | Define a cut-level product coverage requirement: clear package at acquisition/use, readable original logo/`400 TỜ / 4 LỚP` detail, one believable use action, and CTA. Inspect selected takes and final export against the actual original package image, not generated OCR text. |
| A13 | P1 · Open | The source-only `CRB-00016` was started by Administrator on a project owned by `uitest@example.com`; batch ownership became Administrator and variant grouping failed with “These edits cannot be grouped without changing another project family.” The normal-owner request did create a variant. | Make batch ownership and variant creation consistently follow the source project owner for authorized cross-account operations, or reject that operation before queuing. Add an API test for admin-on-behalf-of-owner and a durable failure message. |
| A14 | P1 · Open | Batch API can request 1–20 variants, but this evidence covers only one source-only variant and none that reached a finished auto-rendered film. | Qualify one variant end to end through FrappeUI, approved script, native ComfyUI tasks, take review, audio, export and release gate; then load-test a small batch before claiming 10–20 products/videos. Track queue capacity, GPU/storage consumption, failure isolation and per-variant lineage. |
| A15 | P1 · Open | `PRJ-02593.storyboard_approval_status` is `Draft`. The parent Shera family has 11 open historical feedback records; their applicability to the selected V16 timeline has not been resolved by this audit. Completed export is not release approval. | Run current-timeline feedback mapping and brand/physics/audio review against `ASTV-05069`; resolve or retain each applicable finding with evidence. Only the existing release gate may declare the film publishable. Do not close old findings simply because a newer version exists. |
| A16 | P2 · Evidence gap | Explicit 9:16/30 s was respected in the Shera test, and ratio authority is documented in [input authority](input-authority.md). The automatic path has not been demonstrated with other requested ratios and source-only briefs. | Test the same product-only flow at representative portrait, square and landscape ratios, with format taken from explicit input rather than a reel preset. Assert project, workflow-native alignment and export geometry separately. |
| A17 | P2 · Open | Several older Shera docs describe their then-current working version; they are useful historical evidence but can be mistaken for the latest cut. The selected shot's label/source mismatch compounds this. | Add this issue register to the documentation index/operations handoff, date current-state claims, and link each verification manifest to its exact project and asset version. Do not rewrite historical evidence as if it described V16. |
| A18 | P2 · Not audited to completion | The user requested a whole-project hard-code/maintainability review. This report checked the current creative, reference, video and release paths; it is not a repository-wide proof that every input is configurable or every old branch is removed. | Run a scoped code/config audit with ownership for input authority, workflow JSON sampling/hyperparameters, model adapters, reference roles, camera policy and product-name conditionals. Remove confirmed hard-coded creative inputs only after regression and real-job validation; retain case-specific material in project/workbook data. |

## Required completion sequence

1. Repair **A01–A04 and A09** until a new source-only Shera batch produces an accepted,
   causally complete script. Store rejected-draft evidence and do not render failed
   scripts. The acceptance run must start from the FrappeUI product/mascot references.
2. Repair **A07–A08** so project inputs, reference roles and the versioned workbook
   match the screenplay and selected edit. Freeze those inputs into the native run.
3. Qualify **A05–A06, A10–A12** with actual ComfyUI takes and a decoded 30 s film.
   Compare mascot and packaging to originals, inspect physical transitions and
   camera movement, and listen to the music/voice mix.
4. Close **A13–A16** with owner/API, release-feedback, ratio and small-batch tests.
   Re-export only after the timeline and soundtrack are final; publish only after
   the existing release checks pass.

**Definition of done:** a fresh product-and-mascot-only Shera request yields a
reviewable script, submits real Frappe-to-ComfyUI work, and produces a new 30 s
commercial with accurate original branding, plausible action, motivated camera,
approved sound and a passing release review. The current `PRJ-02593` film is an
available review cut; it is not evidence that this automatic path is complete.
