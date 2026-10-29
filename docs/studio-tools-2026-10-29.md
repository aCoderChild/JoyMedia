# Studio reference tools

The local JoyMedia studio now exposes the requested tools through its existing
project permissions and persistent editing model.

| Control | Behavior |
| --- | --- |
| Templates | Existing template library; applies to the idea or selected scene draft. |
| Plus | Saves a blank five-second scene without invoking AI or starting GPU work. |
| Character mask | Character pictures, shared identity tags, and assignment to the selected scene. The user chose identity/reference management rather than literal face swapping. |
| Storyboard grid | Upload an image, choose 1–6 rows and columns, preview panels, then append every panel as a scene or explicitly replace an equal number of existing scene images. |
| Fit / fullscreen | Canvas framing and native browser fullscreen are separate actions. |
| Playback | Existing two-player video preview; unexported edits also play enabled audio lanes with their trim positions, gain and fades. An exported movie uses its existing mix. |
| SFX | Choose audio or queue effects generation for a rendered scene through the configured effects workflow. Closing the panel leaves the job running; reopening resumes status checks. |
| Broom | Confirmed clearing of all timeline clips, with source scenes and immutable media preserved. Clear persists across reloads and automatic scene synchronization. |
| Three scissors | Trim left, split, or trim right at the playhead. Source offsets and the backend's quarter-second minimum are respected. |
| Undo / redo | Uses persistent timeline snapshots and the existing history stack during the editor session. |
| Scene “Timeline” | Opens an existing scene clip or places a rendered scene into a manually cleared timeline. |
| Cinema export | Explicit 720p or Studio 1440p60 delivery, retaining the project aspect ratio and generation workflow. The UI labels the actual preset instead of promising a generic “2K” output. |

Project owners can use these editing controls. Reviewers and archived projects
remain read-only; backend ownership and write checks remain authoritative.
Manual scenes and grid imports preserve existing scene timings. Replacement
requires matching panel/scene counts and confirmation, so excess panels are
never silently discarded. The server crops actual image bytes and includes
right/bottom edge pixels for non-divisible dimensions. Import metadata is
written in the same transaction, and the most recent 20 request IDs support
safe retries without duplicate scenes.

An SFX job pins the selected source take. If that take changes while the job is
queued or running, its audio is not attached to the new take. Generation is
available only when an effects workflow is configured; uploading audio remains
available otherwise. Tests exercise queueing and recovery with model execution
mocked; no GPU generations were launched for verification.

New schema fields on Media Project are `timeline_cleared` and
`storyboard_grid_imports_json`. They are hidden, read-only, and not copied to
new edits. The local schema was reloaded. Another installation needs its normal
schema migration, the new Python modules, and a rebuilt frontend before these
controls can work there.

Validation: five grid/backend tests, four effects/export backend tests, one
clear/restore/reinsert integration test, six timeline utility tests, and five
browser interaction tests passed. The production frontend build succeeded.
The actual local Shera workspace opens the new dialogs without runtime errors;
its existing scene data was not modified during the UI check.

## Current storyboard editor

The storyboard toolbar now opens the video's saved scenes first, rather than
an empty upload dialog. Scene cards show existing frames/video, descriptions,
durations and whether a frame is outdated. The selected scene has editable
title, description, duration, continuity and caption fields, with explicit Save
and Discard controls. Unsaved drafts survive scene selection; closing asks
before discarding them. A timestamp check rejects stale concurrent saves.

Scene duration changes update total project duration while preserving every
other scene's timing. A title or timing change does not replace technical
generation directions. Editing does not regenerate media or rebuild the cut.
Add, move and remove actions apply explicitly, and removal asks for confirmation.
The existing scene inspector remains available for image/reference tools.

Grid import is a separate tab using the existing import endpoint and retry
semantics. It returns to the current storyboard after a successful import.
The outer editor cannot close while an import request is being applied.
Reviewers can inspect scenes without editing or importing.

## GPU deployment parity verification

Updated the public Tailscale deployment with the same built frontend
(`index-C6sQOBvX.js`, `index-CPfXXCRe.css`) and the required studio APIs.
Added the two storyboard/timeline schema fields. Preserved GPU runtime-specific
generation changes, changing only new-video classification in that module.
Database and replaced application files were backed up under
`/home/ubuntu/joymedia-demo-staging/parity-backup-20261029T002508`.

Authenticated Client checks cover current storyboard display and grid-import
navigation for Shera 14/33 and fashion 5. A rolled-back temporary project verifies
scene add/edit, independent timing, stale-save rejection and no generation jobs.
The browser check also found a missing imported Shera product attachment; restored
the original local image with a private File record attached to its imported Media
Asset. The keyframe API now resolves private image URLs to the exact File identity,
so thumbnails load through the public server. Existing project scenes and video
outputs were preserved.

Screenshots and the final public verification report are retained under
`/workspace/development/verification/deploy-parity-20261029`.

Final public checks: matching frontend asset bytes; no browser runtime errors or
failed HTTP responses; versions and character-reference panels open correctly.
Private playback returns HTTP 206 for Client and HTTP 403 anonymously. No media
generation was started during verification. All eight local storyboard backend
tests passed.
