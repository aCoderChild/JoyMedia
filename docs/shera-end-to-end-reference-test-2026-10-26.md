# Shera reference-to-first-frame verification — 26 October 2026

## Scope

Ran the production `create_product_batch` path using PRJ-02695 as source, with only the original `mascot_front` (ASTV-03707) and `product` (ASTV-03698) reference keys, the original creative direction, 10 seconds, 9:16, Vietnamese, and automatic first-frame preparation. Video rendering was disabled so this test stops at the requested storyboard/first-frame boundary. The variant project may also reuse already qualified character views from the same source family; no hand-selected scene image was supplied.

## Actual runs

| Batch | Variant project | Result | Storyboard shots | First frames | Cause |
| --- | --- | --- | ---: | ---: | --- |
| CRB-00095 | PRJ-02713 | Needs Attention | 0 | 0 | After bounded screenplay repairs, the Director still could not produce a physically coherent action sequence. |
| CRB-00096 | PRJ-02714 | Needs Attention | 0 | 0 | The automatic pose-replanning pass ran once, but opening poses for scenes 1–5 remained unverified. |

The second run requested the same opening state for scenes 1–5: `seated on a rug with both paws free, ready to reach for the tissue pack`. The supplied seated mascot holds a separate heart, while the accepted alternate views in the project family do not establish this seated free-paw state. Pose generation failed qualification, so the system correctly stopped before storyboard import or first-frame submission. Neither run created a Generation Run, and no ComfyUI first-frame task was submitted.

The intermediate second-run screenplay did improve the table reach staging after the automatic replan, but it also showed why text approval alone is insufficient: one earlier draft opened with the bear already holding the pack and then asked it to reach for the pack. A generic validator now catches that conflict in both `visual_camera` and `continuity_rules`. The final accepted script was never admitted to a visual storyboard because its required pose failed qualification.

## General pipeline changes

- A pose failure now triggers one bounded script replan using supplied or qualified character states. This has its own budget and clears stale product/pose preparation flags. The branch executed in CRB-00096.
- The script writer must put the actor and target within natural reach in the opening composition before a grasp. Text review can use an explicit opening state as evidence of reach but never as evidence of contact or a rendered result.
- A deterministic opening/action check rejects a shot that begins holding an object and then acquires that same object, including cases with a brand adjective in only one phrase.
- A terminal pose error now names the required body state, while continuing to block first-frame rendering when it cannot be verified.

## Verification and conclusion

Eight scene-repair tests and the focused opening/action and text-cross-check regression tests passed. Python compilation and `git diff --check` passed. The real Shera run exercised the new pose-replan branch, then stopped at the qualification gate. **This is not a successful end-to-end visual result.** With the current two source images and installed pose generators, the mandatory bear-hand extraction cannot yet be certified as a faithful opening frame. A clean, identity-locked seated action source or a proven character rig/control method is needed before that scene can be automatically promoted. A single product photograph likewise cannot verify unseen printed sides.
