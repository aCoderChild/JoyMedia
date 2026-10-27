# Shera storyboard live audit (2026-10-25)

Scope: references through AI Director, script, pose/product preparation, storyboard, and first frames. No video generation was requested for these trials.

## Existing upstream implementations inspected

- `upstream/Hunyuan3D-2` (`f8db630`): single- and multi-view 3D reconstruction. Its local nodes have no installed model checkpoint or CLIP-Vision model. A single branded pack image also gives no evidence of its hidden print, so this route is not promoted for Shera.
- `upstream/stable-fast-3d` (`ff21fc4`): single-image mesh reconstruction. Its reconstruction cannot certify hidden package artwork, and the production server does not have its weights.
- `../research/refcontrol` (`1e9570b`): reference plus pose/depth conditioning. The project already contains pinned RefControl workflow adapters. The installed human-pose LoRA previously distorted Shera's rounded body; the depth LoRA is absent. Neither is silently promoted to production.
- Existing GroundingDINO/BiRefNet product retention keeps the original visible pack artwork, but that is pixel preservation, not proof of a correct support plane or camera perspective.

## Real Frappe → ComfyUI trials

Both assisted 10-second drafts reused the Shera references from `PRJ-02693` and stopped at storyboard/first-frame review.

| Batch | Project | Script/pose finding | First-frame finding |
| --- | --- | --- | --- |
| `CRB-00081` | `PRJ-02694` | Scripted action order was retained; an earlier pose planner falsely suggested upright for handling scenes without a stand-up. | All five initial frames reached `Needs Review`: a heart leaked from the source character, several actors crossed the table, and product support was wrong. |
| `CRB-00082` | `PRJ-02695` | Explicit stand-up script selected a qualified seated opening pose, then the qualified upright view for later scenes. | Four of five first frames ended in `Needs Review`. The first invented two unrelated retail cartons. Another scripted upright frame was rendered seated on a stool. A later redraw stood the bear but intersected a chair and displaced the product. Only the product-only end card passed its current machine checks. |

Targeted redraw of `SHOT-02884` through `RUN-01263` used the corrected source-prop exclusion. Its first candidate duplicated Shera and was rejected by visual admission. The second still drew a heart in the live mascot's paws, so it stayed `Needs Review`. This proves that prompt exclusion alone does not remove that prop reliably.

The live review model detected the two unreferenced cartons in `GART-03421` and a seated pose in the scripted-upright `GART-03430` when asked focused, structured questions. The physical audit now compares those observations with the actual shot contract. It is a rejection/repair gate, not a generator of correct images; vision judgments can be wrong or contradictory and must not be described as certification.

## First-frame physical review follow-up

The detailed physical audit had run in the automatic batch loop, but the ordinary first-frame consistency worker could mark a manual storyboard frame `Passed` without it. The worker now runs the same script-and-reference-based audit before a `Passed` result. Missing image evidence or an unavailable observer is `Not Checked`; incomplete contact/perspective evidence goes to `Needs Review`. Clear violations remain visible for targeted repair.

A live read-only replay on the current Shera artifacts caught a reviewer parsing error: the product-only end card `SHOT-02893` was described with a fictitious `no figure present` record whose support was `table`. The parser now ignores that absence placeholder. The revised audit returned no findings for `SHOT-02893` and still flagged the unrelated cartons in `SHOT-02889`. This is two observed frames, not a measured false-accept rate; the image model's geometry and identity failures described above remain unresolved.

## Outcome

### Live shot-2 replay (2026-10-26 UTC)

`RUN-01266` completed a real Frappe → ComfyUI keyframe for `SHOT-02890` with the reviewed upright Shera reference `ASTV-06034`. The generated `GART-03445` seated Shera on a chair instead of standing. Both the stored scene check and a separate structured physical audit identified the pose mismatch. I strengthened the compiled opening-pose direction to state the intended weight support explicitly and replayed the same shot as `RUN-01267`. Its new `GART-03447` also seated Shera on a chair, despite the upright source and direction. The package is visible on the table, but that does not repair the pose failure or certify product perspective.

The second stored review stayed at `Needs Review`, but a contradictory yes/no prop-contact answer prevented the structured physical audit from running in the ordinary review worker. The worker now runs that audit even when another visual question fails, and the repeatedly false prop-contact question was removed. This is a review-path correction; the real generated storyboard frame remains physically invalid and must not be approved.

### Product view coverage check

`PRJ-02695` contains one Product Asset Version, `ASTV-03698` (`product.jpg`), and shots 2–5 all bind that same image. The batch recorded no script-requested alternate product views. The photograph shows the front, top and one end; it cannot establish unseen package printing. An isolated call to the configured product-view workflow requested a flatter front candidate. All three generated candidates were rejected by the existing visible-identity check. Visual inspection found missing or altered top/front printing, including the sheet count and paper icon. Rejected previews remain under the site's private `joymedia-product-view-rejections` directory and were not added as selectable Product assets. The client workspace now explicitly reports when only one product photo is selected; a generated view, if one later passes a preliminary check, is labelled an unverified AI candidate rather than an approved source view.

The script-to-pose dependency and product source-art retention work as contracts. The currently installed image model does **not** reliably produce physically valid Shera first frames from those contracts. Keep failed frames in review/redraw, preserve evidence, and do not mark the reference-to-storyboard pipeline robust or automatically approved. A geometry-conditioned image workflow that retains Shera's rounded anatomy, plus repeated real-project acceptance tests, is still required before production promotion.

### Single-image angle feasibility follow-up

The downloaded upstream checkouts were inspected again: Hunyuan3D-2 (`f8db630`) can reconstruct a shape from one image, and Stable Fast 3D (`ff21fc4`) can produce a textured mesh from one image. The connected ComfyUI instance exposes Hunyuan3D node types and a GPU, but its model loader currently lists no Hunyuan3D checkpoint or CLIP-Vision model. Stable Fast 3D weights are also absent; its upstream checkpoint requires gated access. Therefore neither upstream path can run a real Shera 3D test on this installation yet. Their inferred hidden surfaces also cannot certify unseen Shera printing.

The local product-view binding now rejects AI candidates as additional *real* photos for multi-view reconstruction and prioritizes supplied photos over generated candidates when both claim the same angle. Thirteen product-view contract tests pass. A live, read-only `PRJ-02695` check found exactly one product reference (`ASTV-03698`, view `source`), reported reconstruction input `ready=False`, kept that photo for an ordinary tabletop shot, and marked a requested rear shot unsupported while binding the same source. This verifies the safety behavior on the actual project; it does **not** deliver all-angle product media or verify scene-camera alignment. The earlier three real generated front candidates failed identity review. Acquiring approved multi-angle photography or installing and validating a suitable single-image reconstruction workflow remains necessary for the requested result.

### Uploaded angle-sheet test (2026-10-25 UTC)

The site's existing `ASTV-05260` is one uploaded five-view Shera 400-sheet / 4-ply contact sheet, not five individually selectable project references. Its top row shows front-left and front-right three-quarter views; the bottom row shows left, right and top/front views. I cropped its five image regions into private test files under `sites/joymedia.localhost/private/joymedia-product-angle-tests/2026-10-25/`. These test crops are source material from the uploaded sheet; the sheet does not independently verify hidden printing or a rear view.

The existing `split_view_sheet` handles side-by-side character sheets and returned zero crops for this two-row product sheet. I added distinct `front_left`, `front_right` and `top_front` Product View labels and reloaded the Project Reference DocType. A real-image binding test used all five crop bytes and confirmed that the script requested five distinct views and that each shot resolved to exactly one matching crop. The product-view and character-sheet tests pass (17 total). This test used temporary reference rows and did not alter `PRJ-02695`.

The original broad palette check accepted a different pink 300-sheet Shera product because both images had white studio backgrounds. The revised check compares chromatic product pixels: it accepted all five blue 400-sheet crops and rejected that pink product. The vision identity judge accepted the pink product in one trial despite a stricter prompt, so its answer is not sufficient evidence on its own; human print review remains required. The identity prompt was also changed to request an explicit `answer` boolean: before that change, a positive `same_design` response was parsed as failure. Therefore the earlier three candidate rejections cannot be attributed solely to image mismatch, although direct visual inspection still found altered print.

Two real `WF-02656` ComfyUI keyframe runs used the individually cropped front-left and front-right source images and the same cozy-room/tabletop direction. Outputs are `front_left_34-room.png` and `front_right_34-room.png` beside the crops in the private test directory. Both rendered one supported package on the table, but the output orientations converged on a similar visible short end and small print was distorted. These first frames fail exact product-angle and artwork acceptance. The current pipeline can select the requested input image but does not yet make the image generator obey its camera orientation or preserve fine printed art.
