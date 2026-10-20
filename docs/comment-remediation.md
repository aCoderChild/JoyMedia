# Turning review findings into verified corrections

Review records stay attached to their original immutable outputs. A direction
change is preparation; a corrected starting image is a candidate; a repaired
take is local evidence. None alone certifies a complete commercial video.

Use existing implementations by defect type:

| Finding | Existing implementation | Acceptance |
| --- | --- | --- |
| Flat package/logo artwork drifts or looks pasted | OpenCV SIFT/RANSAC tracking, perspective warp, optional `seamlessClone`; existing source-art repair worker | Every visible frame tracks; surface placement, occlusion and brand colors reviewed; source and output hashes retained |
| A limb changes shape, support geometry fails, an action has the wrong cause | Existing guided-video API and VACE reference/control/masked-edit inputs | Correct opening plus visible ownership/contact/cause throughout the action; no automatic promotion from a sampled pass |
| An idle object loses material | Authored material-state invariant, then constrained scene regeneration | Fill/state stays fixed when no transfer event occurs; no flat-patch shortcut for changing 3D perspective |
| Multi-view reference becomes multiple actors | Existing single-view asset and canonical `identity_key` grouping | One physical actor; alternative views remain reference history, not separate cast members |
| Embedded shot speech/music doubles the authored soundtrack | Existing linked Source clip mute, separate VO/BGM/SFX timeline | Export manifest contains the intended layers only; durations and dialogue spans checked |
| New export hides earlier unresolved findings | Existing immutable export timeline and release feedback guard | Applicable findings follow reused footage and copies; whole-video issues require explicit triage |

Repositories inspected:

- [VACE](https://github.com/ali-vilab/VACE), checkout
  `48eb44f1c4be87cc65a98bff985a26976841e9f3`: use its documented source video,
  mask and reference-image semantics through the existing workflow contract.
- [Story2Board](https://github.com/DavidDinkevich/Story2Board), checkout
  `92ef11077c3a596a32241e434b0c527ec54f2546`: shared identity anchoring is useful
  for story panels; it does not establish physical contact or exact package text.
- [PhysGen](https://github.com/stevenlsw/physgen), newly cloned for inspection at
  `67fe0f2909bc332f0d8f1da1cd94c5fe245a9bfe`: separates perception, Pymunk rigid
  simulation and diffusion refinement. Its 2D rigid simulation is not a fluid
  solver. No top-level license was present in the inspected checkout, so its
  source was not incorporated into the commercial runtime. Existing Pymunk
  integration remains the rigid-motion guide implementation.
- [OpenCV](https://docs.opencv.org/4.x/df/da0/group__photo__clone.html): reuse its
  tracking, geometric transformation and Poisson compositor implementations.
  No new tracking or blending algorithm was written.

These mechanisms use supplied assets, regions, event constraints and workflow
capabilities. Production code contains no product-name branches or default
four-leg, mascot, tissue or container requirements. Case-specific constraints
belong to project records; the shared tests include unrelated product shapes and
passive material states. These tests validate contracts and rejection behavior,
not physical understanding by an unavailable inference model.
