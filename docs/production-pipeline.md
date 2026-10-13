# Fixed FLUX → H3 production pipeline

JoyMedia deliberately uses one promoted, immutable production pipeline.  It does
not select a workflow from the number or type of references in a scene.

## Promotion

1. Register and validate an immutable FLUX keyframe workflow and an immutable H3
   video workflow against the actual ComfyUI server.
2. Create an immutable `Generation Pipeline` whose first step is FLUX and whose
   final step is H3.
3. Smoke-test that exact pipeline with a real FLUX → H3 render.
4. Promote it deliberately only after the test passes:

   ```bash
   bench --site <site> set-config joymedia_active_generation_pipeline <pipeline-name>
   ```

Creation of a workflow or pipeline does not promote it.  The production route
fails closed if that setting is missing, points to no record, is not linear, or
does not expose bindings for the project's selected references.

To roll back, promote the previously smoke-tested immutable pipeline name with
the same command. Existing runs retain their pipeline snapshot.

## Shera storyboard workflow

1. Create a project and enter a non-empty creative prompt.
2. Upload product artwork, both mascot references, and the official product PDF
   as project material. Verify mascot identity in approved keyframes before a
   production render; PuLID is a FLUX enhancement, not proof of animated-bear
   consistency.
3. Export the source Google Sheet as `.xlsx`, import either `Demo 1` or `Demo 2`,
   then review the preserved Vietnamese copy, timings, and reported gaps.
4. Mark each scene as `Continue` only for a deliberate continuous action. Leave
   new locations, new compositions, montages, and end cards as `New Scene` so
   FLUX makes a fresh starting frame.
5. Approve the storyboard. Any scene, timing, keyframe, reorder, or removal edit
   returns it to `Ready for Review`; rendering is blocked until re-approved.
6. Render approved shots, review takes, then export. Caption overlays are drawn
   by FFmpeg from the stored source text. Product art, end cards, split screens,
   and voice-over must use approved deterministic media/timeline assets rather
   than relying on generated lettering.

`Demo 2` has unauthored time ranges. The importer reports them and requires an
explicit acknowledgement; it never invents content for those ranges.

## Current supplied assets

`workflows/minimax_h3_tung.json` is registered as the H3 stage only. Do not
promote a pipeline until a real, compatible FLUX workflow (and any intended
PuLID bindings) has been registered and validated on the target ComfyUI server.
