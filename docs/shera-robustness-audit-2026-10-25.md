# Shera automatic reference and physics audit — 2026-10-25

The diagnostic used the original mascot and package references from `PRJ-02696` in a new project, `PRJ-02702` (`CRB-00087`). It was cancelled after the first frames exposed unresolved visual defects; it did not produce an approved video.

## Observed

- The screenplay reached rendering, but it had seven scenes despite an explicit five-shot direction. It reused a seated mascot and repeated static product presentations. Explicit shot count is now a hard script constraint.
- Three product angles passed the candidate checks: front-left, front-right, and top-front. The side candidate failed geometry/identity checks and remained `source_locked`. An explicit missing angle now stops automatic rendering with a request for a real side photo.
- The old per-shot planner dropped the scripted product angle and bound `ASTV-03698` (the source) in `SHOT-02908`, even though a checked front-left candidate existed. The handoff now uses the authored opening camera view. A real-project check maps scene 1 to `product_view_9ddea19933b8`.
- Mascot pose preparation deferred scenes 1–4. The first generated frame (`/private/files/TASK-02465_ATT-02287_00001_.png`) retained the source pink heart; the pack showed a white rectangular studio patch on the table. The physical review already rejected mascot scale. The new independent matte review also rejects that exact frame.
- Six of seven first frames were redrawing for geometry, support, scale or table-leg failures when the batch was cancelled. The seventh packshot was marked Passed although visual inspection showed a pack too large for its furniture. The current vision observer also called that scale plausible when asked directly. This is an unresolved automatic scale-verification limit.

## Implemented guards

- Script-level package support continuity and explicit shot-count validation.
- Partial pose-plan completion request; an incomplete result still defers instead of fabricating states.
- Independent product-angle geometry/identity verification; old unchecked candidates cannot be selected.
- Authored product angles survive per-shot planning.
- Product white-matte and undeclared foreground-human checks in first-frame review.
- Explicit requested angles fail early when no verified candidate or supplied view exists.

## Remaining requirement

One front package photo does not establish hidden side printing. A real side photo is needed to fulfill the requested side view. A physically measured package width and support width, or a reviewed placement, is needed to certify scale; the current visual model can miss an oversized package. The original mascot reference contains a held pink heart, and the automatic pose generator has not produced accepted clean action poses from it. The diagnostic is a failure case, not proof of automatic end-to-end completion.
