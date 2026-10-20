# Correct footage before release

Use the same procedure for every product, actor and rendering workflow. Product
names do not select geometry rules or override review findings.

1. Establish the scene's entities, connected parts, support, scale and event
   order before generating motion. Counts describe physical units separately
   from constituent layers or printed artwork. Use approved source references.
2. Check the actual starting image. A prompt mentioning a chair does not prove
   seating support; a package reference does not prove exact logo preservation.
   Store externally generated images as unapproved imported candidates with
   provenance, never as fabricated internal generation attempts.
3. Use a short interaction and fixed camera where possible. When topology or
   contact fails, use authored geometry/motion guidance or a controlled editing
   workflow that declares the required input roles. Inspect installed capabilities
   after a server restart. Do not silently downgrade to unconstrained generation.
   [VACE's official guide](https://github.com/ali-vilab/VACE/blob/main/UserGuide.md)
   describes reference, control-video and masked-editing approaches; these are
   conditioning tools, not guarantees of correct physics or identity.
4. Review start, contact, action and end frames, including ownership of limbs,
   fluid origins, stable object scale and visible construction. Use temporal
   evidence conservatively. Preserve exact artwork with suitable perspective,
   tracking and occlusion; reject uncertain placement rather than floating labels.
5. Keep embedded shot audio separate from authored narration/music. If source
   audio contains unwanted speech/music, mute its linked Source clips explicitly.
   This does not isolate Foley. Generate or author a separate effects layer if
   needed; do not claim effects were preserved after muting the mixed stream.
6. Retain prior cuts, exact-version comments and take lineage. Review exports
   may retain known defects; release exports require current scene approval and
   resolution of applicable feedback. Re-exporting or copying footage is not a
   resolution.

`review/release_feedback.py` maps unresolved full-cut frame/range comments through
the immutable rendered segments, including both inputs during a dissolve. A
finding follows reused sources across edit versions and `derived_from` copies.
Replacing the affected footage can remove its relevance; unrelated changed shots
cannot. Video-wide comments and missing timing evidence require explicit triage,
because changing pictures alone cannot establish that audio or edit issues are
fixed. Closed findings remain in the original version's history.

When inference is unavailable, retain the selected cut, record unapproved
candidates and the failed preflight, and complete independent edits. A still
candidate or an unchanged video stream must never be reported as regenerated
moving footage.
