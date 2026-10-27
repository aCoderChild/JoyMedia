# Shera two-reference automatic video test — 2026-10-26

## Scope and inputs

- Fresh source project: `PRJ-02703`. The only uploaded inputs were `mascot_front.jpg` (`ASTV-03707`) and `product.jpg` (`ASTV-03698`).
- Final diagnostic variant: `PRJ-02707`, batch `CRB-00091`. Portrait, Vietnamese, 30 seconds, automatic script and first-frame generation. The brief requested five narrative beats, physically supported mascot actions, front-left/front-right/top-front pack views, exact visible print, and white-background reference variants.
- Earlier diagnostic batches: `CRB-00088` exposed a negative-angle parsing bug; `CRB-00089` exposed a pose-planner identity-alias bug; `CRB-00090` exposed a conflicting five-shot/30-second constraint and was cancelled. These are kept as diagnostic records, not successful videos.

## Observed result

| Stage | Result |
| --- | --- |
| Script | Seven scenes total exactly 30 seconds. It names seated, standing, reaching, tissue handling, and product-only scenes. Director warnings remain for an idle opening and a later idle reaction scene. The renderer's 124-frame shot limit cannot fit 30 seconds into five shots at 24 fps; the final brief permitted splitting five narrative beats into seven shots. |
| Product views | Three AI-extrapolated candidate references were prepared and labeled front-left, front-right, top-front. They are **not verified package artwork**. The front-left and front-right images visibly distort small print; the left candidate invents a barcode on an unseen end. |
| Mascot pose preparation | No generated Character view passed qualification. All five mascot scenes have `status=deferred`; the H3 bridge reported that it did not produce a qualified seated or standing pose. No clean standing or action pose was bound. |
| Storyboard | Seven `Shot` rows were imported for `PRJ-02707`. The workbook and scene bindings exist, but the script and input-view defects remain. |
| First frames | Seven initial first frames were generated. All seven were marked `Redrawing`. First-frame examples retain the pink heart, break table/body geometry, or show a seated mascot in a standing shot. A redraw of shots 1 and 2 still retains the heart; shot 2 remains seated. Product lettering and side artwork remain unreliable. |
| Video | No approved storyboard/video export. The batch was cancelled after the redraw evidence confirmed the same defects. Project export and post-production remain `Idle`; a generated video would not satisfy the source and physical checks. |

### Visual evidence

- Supplied product: `sites/joymedia.localhost/private/files/product.jpg`.
- AI front-left and front-right candidates: `sites/joymedia.localhost/private/files/product_view_3c5fbc059af8.png`, `sites/joymedia.localhost/private/files/product_view_8f71e04c6db1.png`.
- Initial scene 1: `sites/joymedia.localhost/private/files/TASK-02485_ATT-02300_00001_.png` — heart retained; bear overlaps table.
- Initial scene 2: `sites/joymedia.localhost/private/files/TASK-02486_ATT-02301_00001_.png` — seated rather than standing; heart retained.
- Initial scene 3: `sites/joymedia.localhost/private/files/TASK-02487_ATT-02302_00001_.png` — pack too large and print altered.
- Initial scene 4: `sites/joymedia.localhost/private/files/TASK-02488_ATT-02303_00001_.png` — mascot/table intersection and incorrect pack orientation.
- Scene 1 redraw: `sites/joymedia.localhost/private/files/TASK-02492_ATT-02307_00001_.png` — heart persists.
- Scene 2 redraw: `sites/joymedia.localhost/private/files/TASK-02493_ATT-02308_00001_.png` — still seated and heart persists.

## Changes made during the diagnostic

1. `requested_view_sequence` now ignores negative safety instructions such as “Do not invent hidden side printing” rather than treating them as client angle requests. Regression test added.
2. The script validator now recognizes hyphenated instructions such as “five-shot screenplay.” Regression test added. This revealed the workflow capacity conflict, so the final diagnostic brief allowed enough shots for 30 seconds.
3. The pose planner now normalizes an unambiguous identity alias to the exact cast reference and collapses duplicate responses, preferring the exact key. Regression test added.

The focused regression tests passed. A broader 208-test run finished with 3 failures and 1 error in existing creative workflow/gallery expectations; it was not a clean full-suite result.

## Conclusion

This real two-input test does **not** verify reliable automatic mascot pose variation or faithful multi-angle product rendering. The angle candidates are generated, but visible package details are not trustworthy. The pose subsystem correctly declined every new mascot pose, while first-frame generation still drew from the heart-holding source and failed physical/identity review. Production use requires a clean prop-free mascot reference or a pose generator that passes the existing qualification gate, plus actual package-view evidence or a stricter exact-artwork gate for AI candidates. The current batch must remain a failed diagnostic rather than a completed project video.
