# Shera repository trial — 26 October 2026

This is a research trial on the real Shera pack and room references. No project
asset, storyboard frame, workflow mapping, or production model was changed.
Private outputs are in
`sites/joymedia.localhost/private/joymedia-research/shera-repo-trial-2026-10-26/`.

## Candidates and runtime

| Candidate | Source | Trial status |
| --- | --- | --- |
| Existing OpenCV/Pillow tabletop compositor | `joymedia/services/keyframes/product_composite.py` | Ran on the Shera room with the original RGBA cutout and an existing generated front-right cutout. |
| Hunyuan3D-2mini | `upstream/Hunyuan3D-2` (`f8db630`), isolated checkpoint `tencent/Hunyuan3D-2mini` | Downloaded only the mini shape checkpoint and ran a 10-step CPU reconstruction. No production ComfyUI model was installed. |
| TRELLIS | `upstream/TRELLIS` (`442aa1e`) | Cloned and inspected; no checkpoint or inference run. Its documented path needs a separate CUDA environment and at least 16 GB VRAM. |
| AniGen | `upstream/AniGen` (`c49db3d`) | Cloned and inspected; no checkpoint or inference run. Its included CUBVH component carries a non-commercial/research-only NVIDIA license, so it is not a production candidate for commercial videos as packaged. |
| Stable Fast 3D | `upstream/stable-fast-3d` (`ff21fc4`) | Previously cloned. No weights on the production server; not rerun. |

## Real-reference result

The compositor used `product-rgba.png` and
`location_65586b8386b262cc.png`. A hand-selected table quadrilateral and
**estimated** product/table width fraction of `0.34` produced
`shera-estimated-tabletop.png`. It recorded five contact points and a
`145 × 82` pixel product box in the 1280 × 720 frame. The second trial reused
the same placement with
`product_front_right_cutout_c1329721c127828b0b.png`, producing
`shera-generated-front-right-tabletop.png`. Both passed the compositing code's
2D support and baseline-angle checks, and visual inspection found neither
oversized on that room table. The generated front-right image is an unverified
AI view; its small print cannot be treated as authentic packaging evidence.
The `0.34` fraction is an estimate, not a measured scale, and the table polygon
was selected manually. These are review candidates, not automatically approved
project frames.

Hunyuan3D-2mini loaded in an isolated Python environment after pinning
`transformers==4.48.3` and `diffusers==0.32.2`; the production ComfyUI environment
has newer versions. Its real Shera product run completed in about 234 seconds
on CPU with 10 inference steps and octree resolution 128. The mesh has 39,716
vertices and 79,428 faces; `product-10step.glb` and five orthographic shape
renders are saved with the tabletop outputs. The inferred object is a plausible
soft rectangular pack silhouette. This shape-only run supplies no texture or
verified printing for a hidden side. The shared GPU was fully occupied during
the trial, so a full-quality 3D comparison was not attempted.

The original `mascot_front.jpg` visibly contains a pink heart held between both
paws. A generic single-image reconstruction would receive the heart as part of
its input; this trial did not produce a clean, independently poseable mascot.

## Decision for this case

Use the supplied product pixels and the measured tabletop compositor for
opening frames when the requested face is genuinely visible in a supplied,
approved view. Require either product and table widths or an explicit reviewed
scale estimate; a 2D contact pass alone is insufficient. A reconstructed 3D
mesh can be a camera/shape proxy, but must not be promoted as evidence of
unseen brand artwork. A branded side shot still needs a real side photograph or
approved artwork mapped to that side. Keep the current unsupported-angle gate.

For the mascot, first obtain or approve a prop-free identity reference and
qualify a limited pose library against physical support and identity. Do not
integrate AniGen into commercial production on this packaged license, and do
not promote inferred pose variants solely because a model produced them.

Validation: `env/bin/python -m unittest
joymedia.tests.keyframes.test_product_composite
joymedia.tests.planning.test_product_views -q` — 29 tests passed.
