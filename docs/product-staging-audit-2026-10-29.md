# Product and staging audit — 29 October 2026

Scope: the product appearance and scene logic in
`PRJ-02724-edited-b8adac7b.mp4`. The user asked to retain the mascot's established
identity and appearance while increasing its scene scale.

## Findings

- The selected product lock used ASTV-06331, an AI-generated alternate view,
  instead of the supplied ASTV-03698 photo. The generated view shortened the
  package and omitted readable print. Lost view metadata had also made it appear
  eligible as a supplied source.
- Preserving RGB and aspect ratio did not establish correct placement. The
  compositor covered a detected footprint by expanding one dimension of the
  replacement image, leaving its support, camera perspective and shadow behind.
  Replay of saved lock evidence rejects two of the three product-bearing frames
  under the new footprint check; the second frame's small expansion is within
  the registration tolerance and still needs independent support review.
- The second and third scenes place the actor on or through the table despite
  authored rug support. Live support observations flag both as violations.
- Static product locking bridged short appearance gaps, potentially painting
  through a paw crossing. Mean image similarity alone cannot establish correct
  occlusion.
- Camera and silhouette guidance skipped opaque product photographs. The real
  JPG consequently lacked guidance available to the altered prepared view.
- Relative-size controls did not express character-versus-product scale in the
  drawing prompt. Source-image framing is not physical size.

## Changes

Strict source-pixel mode now selects supplied product views or their qualified
cutouts. An AI angle remains an explicitly inferred preview, including when a
language-model identity judgment passes. Missing-angle fallbacks name the actual
chosen source view. Derived views with erased provenance do not become supplied
photos, and no unqualified view is used as a last-resort source. Preview
qualification now separately records identity, panel proportions and shared
print, with a version preserved through caption refresh.

Prepared overlays must stay within 5% per edge (at least two pixels for rounding)
of one measured detection. This is a registration tolerance, not a physical-size
measurement or perspective guarantee. Short coverage gaps are no longer bridged;
incomplete coverage requires tracked, occlusion-aware repair or remains held.

Opaque JPGs now supply camera guidance. Measured source-matte proportions are
stored privately by immutable source hash and pinned preparation recipe, independently of
whether placement passed. A failed scene cannot thereby become accepted. The
stored measurement survives cache eviction and rejects other sources/recipes. The
original product's measured outline is approximately 1.77:1, rather than the
altered view's approximately 1.3:1. Scene scale now follows the existing relative
size controls without changing pose, anatomy or crop. Size changes require an
idle project and invalidate storyboard approval.

## Local verification and project state

Evidence is under
`/workspace/development/verification/product-staging-20261029/`.

The mascot images ASTV-03707 and ASTV-06332 and their appearance metadata were
hash-checked unchanged. Their project-relative size was changed from 1 to 2;
product size remains 1. This is a composition setting, not a redraw or identity
replacement. The old MP4 and selected video takes were not replaced.

The existing project was replanned through the normal application job. Its stale
closing direction was corrected through normal shot/reference APIs, keeping the
declared product-only ending and original product source. The revised plan was
reviewed through the normal storyboard API. These are operator repairs, not an
uninterrupted zero-intervention demonstration; no generated frame/take was
manually approved.

Native first-frame RUN-01366 tested the two reported scenes with the original
product and unchanged mascot pose asset. Scene 3 produced
`TASK-02726_ATT-02576_00001_.png`: the actor sits on the rug outside the table and
holds a paper sheet. Native admission completed; this remains a review candidate.
Scene 2 was held by the new product-footprint check. Its failure exposed the
opaque-reference guidance omission above. A bounded retest uses the measured
original outline and camera guidance in RUN-01367 after replanning that scene.

RUN-01367 was held because the original source could not fit the generated
footprint. The raw image still put the actor on the table. A further layout test
uses the already-qualified empty floor plate ASTV-06382 as an explicit environment
reference. The initial RUN-01368 binding was automatically replaced by the old
room because its imported key used the reserved `location_` prefix; that owned
test was cancelled. RUN-01369's frozen inputs were verified as ASTV-06332
(unchanged actor), ASTV-03698 (original product), and ASTV-06382 (empty floor).
Its raw image places the actor on the rug beside the pack, with more actor scale.
Product preparation still rejects the mismatching footprint. This is an improved
layout candidate, not an accepted replacement shot. Scene 3 also remains Needs
Review because screening cannot establish the scripted tissue-held-to-light action.
No new frame/take was manually approved and no new full video was exported.

The local vision model incorrectly accepted the altered product print in a live
paired comparison. That evidence is retained in
`old-product-view-source-comparison.json`; it is why a model verdict cannot
authorize invented packaging in strict source-pixel mode. Likewise, a passed
sample does not certify every video frame or a package-opening action. A corrected
full replacement MP4 has not yet been verified.

Targeted backend checks passed across 13 modules (239 tests), including source
selection, silhouette persistence, opaque-photo viewpoint guidance, physical
contracts, compositing, tracking and project controls. Ruff, format and diff
checks passed. These regression checks do not establish final visual acceptance.
