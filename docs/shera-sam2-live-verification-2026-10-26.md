# Shera source-art and first-frame verification — 26 October 2026

## Scope and strategy

Used Meta SAM 2.1 (upstream commit `2b90b9f`, Apache-2.0) in an isolated Python
worker to prepare exact-RGB transparent references. The commercial storyboard
remains script-led: a scene's action and opening camera determine required
mascot pose and package orientation, followed by reference preparation. The
current imported Shera script requests standing and waving actions, but none of
its five scenes names a new package-facing angle. Its product view requirement
is `source` in every product-bearing scene. The five sheet crops are useful
intermediate candidates, but their geometry and unseen artwork have not been
independently confirmed.

## Intermediate assets in PRJ-02695

| Asset | Selected reference | Qualification |
| --- | --- | --- |
| Seated mascot source matte | `ASTV-06231` | Source RGB identical; clean alpha |
| Standing mascot matte | `ASTV-06234` | Source RGB identical; clean alpha; derived pose already qualified |
| Waving mascot matte | `ASTV-06224` | Source RGB identical; clean alpha; derived pose already qualified |
| Original product matte | `ASTV-06238` | Source RGB identical; clean alpha; canonical identity repaired |
| Right, front-right, left product sheet mattes | `ASTV-06235`, `ASTV-06236`, `ASTV-06237` | Clean alpha; **view geometry and unseen print unverified** |
| Front-left, top-front product sheet mattes | `ASTV-06226`, `ASTV-06228` | Clean alpha; **view geometry and unseen print unverified** |

The RGB check compared every prepared matte above with its source pixel for
pixel; all matched, and each alpha channel spans 0–255. The new mask selector
rejects retained studio scraps using connectedness, source-foreground retention,
contour roughness and a visual review on dark gray. It does not prove that an
AI-derived pose or unseen package panel is authentic.

## Live project test

The approved project scene 2 was rebound to standing matte `ASTV-06234`,
product matte `ASTV-06238`, and the existing clean living room reference.
First-frame run `RUN-01296` generated two saved proposals:

- `GART-03521`: `/private/files/TASK-02510_ATT-02322_00001_.png`
- `GART-03523`: `/private/files/TASK-02510_ATT-02323_00001_.png`

**Result: failed visual admission.** The inspected second proposal draws two
physical bear mascots and stages them on the tabletop; the tissue pack is too
large for a plausible tabletop placement. The exact product source artwork was
retained in a patch, but pixel fidelity alone did not fix scene geometry. The
previous project keyframe remains saved and marked Needs Review. No new
proposal was promoted as a usable storyboard frame or sent to video generation.
An independent character-body count now reports two bodies for this real frame
against the script's one declared character. The physical audit also flags
table support and source-fit uncertainty.

## System changes and checks

- Exact cutout creation now inherits the canonical identity even when its
  original row has no explicit identity key. Existing Shera product mattes were
  repaired, and script-led product preparation now chooses `ASTV-06238`.
- Unverified product sheet crops and their masks cannot silently satisfy a
  scripted angle. They remain in the project as reviewable intermediates.
- The first-frame review independently counts physical actor bodies; it holds
  a missing, duplicate, or uncertain cast count.
- The AI script writer now names a changed package orientation when the shot
  needs one; pose and view preparation still follows the completed script.

Tests passed: product-view contracts (26), pose coverage (36), physical audit
(16), reference fit (2), and product compositing (7). The broad creative module
has two remaining workflow test failures outside the product-view contract
tests; do not treat the whole creative module as green.

## Remaining production limit

This run did **not** achieve reliable automatic first frames or factual product
multi-angle coverage. A single real front/three-quarter product photo cannot
verify hidden packaging print. The current image workflow can ignore count,
support and scale instructions even with clean cutouts. The system now retains
the intermediate references and rejects such bad first frames instead of
approving them. A final commercial frame requires a compatible scene renderer
or an approved placement with physical scale evidence; unknown package panels
need real reference photos or explicit product-art approval.

## Limb-topology follow-up

The selected standing/waving mascot images have rounded, short limbs, while
the saved scene frames redraw them with elongated/narrowed arms or an extra
paw. A dedicated source-paired limb check found these mismatches on actual
project artifacts `GART-03517` (scene 2), `GART-03506` (scene 3), and
`GART-03513` (scene 4). All three shots remain **Needs Review** with the
specific finding attached. The same check now runs before selecting a newly
generated first frame; a witnessed distortion rejects that candidate, and an
unverifiable result cannot count as a pass.

This is an admission fix, not a corrected render. The selected reusable body
poses do not show the scripted pack/tissue contact in scenes 3–4, so a scene
renderer may still invent hands. A reliable replacement needs an action-
compatible mascot asset or an exact-art scene composition with qualified
contact and support. The current three frames must not be treated as finished.

### Script-led pose preparation trial

The current `PRJ-02695` director script produced four opening-state requests:
supported standing with both paws free; supported standing with a paw reaching
toward the table for two scenes; and supported standing with one paw raised for
the final handling scene. The preparation run used the selected mascot media
and the installed H3/still workflows. Every requested state was **deferred**
after pose, support, and identity qualification; no generated pose was added to
project media. The repeated reaching state now shares a failed-candidate key
within a run, avoiding a redundant generation attempt. These results do not
establish that the system can automatically provide the requested mascot poses.

The requirements and review prompts use script actions, asset lineage, and
visible anatomy rather than project-specific names or hard-coded scene IDs.
The admission check prevents these known distorted frames from being counted
as qualified output, but the underlying image model still needs a reliable
action-compatible character pose or scene compositor to produce replacements.
