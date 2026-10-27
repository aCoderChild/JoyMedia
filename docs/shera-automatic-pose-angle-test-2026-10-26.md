# Shera automatic pose and product-angle test — 26 October 2026

## Scope

Created test container `PRJ-02696` with only the original Shera mascot reference `ASTV-03707` (`mascot_front`) and original package reference `ASTV-03698` (`product`). Submitted automatic batch `CRB-00083` with a 30-second brief requesting distinct seated, standing, reaching and tissue-holding mascot poses, and front-left, front-right, side and top-front product views. The batch created video project `PRJ-02697` with seven scenes. The source project `PRJ-02695` was not modified.

## Observed result

**Fail: the system did not automatically produce the requested pose and angle coverage from these two inputs.** The completed script did not name product orientations in its scene camera descriptions; `product_views` was empty, and the generated project retained the original product reference as its only Product asset. All five requested pose-preparation entries were `deferred`. The logged reason was `No prop-free identity view is available for reusable pose generation.` The source mascot holds a pink heart.

Seven first-frame artifacts were saved. Scenes 1, 5 and 6 were machine-marked Passed; scenes 2, 3, 4 and 7 required review. Visual inspection found the bear still seated on the tabletop in Scene 2, despite its standing/reaching beat. Scene 3 initially intersected the tabletop; Scene 4's final frame has a critical support/product geometry finding. Scene 6's beat says the bear holds a tissue, but the saved image shows human-looking foreground figures and a pack on the table. Its machine Passed status is therefore a false negative for the requested scene content. Scenes 1 and 5 reuse the source-facing package artwork; Scene 5 does not demonstrate a new package angle.

The automation attempted several redraws and two scene rewrites. It then moved to a fresh concept without fixing the fixed source-pose limitation. The diagnostic batch was cancelled to avoid further GPU retries on unchanged inputs. No scene video clips or final video were produced. The generated project and first-frame artifacts remain available for inspection.

## Evidence

| Scene | Final frame | Saved review state | Observed issue |
| --- | --- | --- | --- |
| 1 | `/private/files/TASK-02436_ATT-02264_00001_.png` | Passed | Seated source-like bear holding heart; source-facing pack. |
| 2 | `/private/files/TASK-02443_ATT-02271_00001_.png` | Needs Review | Bear seated on tabletop instead of standing/reaching. |
| 3 | `/private/files/TASK-02438_ATT-02266_00001_.png` | Needs Review | Critical pose/support geometry. |
| 4 | `/private/files/TASK-02453_ATT-02281_00001_.png` | Needs Review | Critical character/product support geometry. |
| 5 | `/private/files/TASK-02440_ATT-02268_00001_.png` | Passed | Product-only packshot, same source-facing angle. |
| 6 | `/private/files/TASK-02441_ATT-02269_00001_.png` | Passed | Human-looking figures appear instead of scripted bear action. |
| 7 | `/private/files/TASK-02447_ATT-02275_00001_.png` | Needs Review | Geometry qualification uncertain. |

This is a real end-to-end attempt through planning and first-frame generation, but **not a completed video quality pass**. A reliable automatic pass needs a prop-free mascot identity reference, explicit product-view requirements in the actual storyboard, and stronger content checks that compare the generated frame against the cast and action before allowing a Passed state. Hidden product panels still require real approved photos to be treated as factual packaging.
