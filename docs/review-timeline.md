# Storyboard and video review timeline

The guided workspace shows the current storyboard, first frames, approval/staleness and authored logic checks. This plan is separate from the footage in a saved export. Scene thumbnails open individual takes; the full-video timeline seeks inside the saved file.

The review timeline has a frame slider, timecode, exact-video thumbnails, zoom, scene starts, comment pins and ranges. Clicking a pin opens its original immutable version and frame. Comments, ranges, problem categories, marked areas and administrator responses stay in Frappe Video Review Feedback records. Saving a comment refreshes the main timeline; it never generates a job or approves footage.

Detailed review is embedded beside the preview player. Pause or enter a frame number, then choose **Spot** or **Box**. Spot records one normalized point; Box records a normalized rectangle. Write the problem and submit. Each record freezes the source edit, video asset version, frame or range, author and coordinates. Clicking its timestamp restores the frame and mark. The selected comment appears first in the side panel, including when opened from a timeline pin or a historical version. Left/right arrows step frames while the video surface has focus. Frame numbers shown to reviewers start at 1; stored frame indices start at 0.

Marks use the video's own aspect ratio and normalized coordinates, so resizing preserves their location. Selecting a tool brings the paused frame into view, and pointer input waits for seeking to finish. Frame indexing tolerates browser microsecond truncation at frame boundaries. Point and box evidence cannot be rewritten by administrator triage; status and response remain editable under the existing administrator permission. Review tools are available only when the account may submit feedback.

New exports freeze the renderer's actual scene timing, including trimmed sources, positioned gaps and transition overlap. Older exports without that evidence show a notice and no invented scene boundaries. Reviewer timing uses the same exact-version publication authorization as playback and strips internal directions. Range widths scale with timeline zoom. Thumbnail extraction is bounded and cancelled when the video changes or the component closes.

A revised direction or physical contract is compared to the selected take's original generation snapshot. Old footage stays available for review, but cannot count as newly generated footage. Stale first frames lead back to preview generation. Release rejects outdated known direction, missing brand approval and unresolved scene review records. Sampled vision checks do not prove fine identity, exact typography or all-frame physical correctness.

Shera verification: `verification/shera-timeline` outside the Bench contains the real 30-second review export, timing, sampled video evidence, seven actual defect reports and six prepared four-leg-table scene contracts. This export reuses saved footage and remains unapproved. Corrective GPU generation is blocked while the configured SSH/ComfyUI connection refuses requests. No corrected four-leg table footage is claimed.

Reference interaction: [CapCut keyframes](https://www.capcut.com/resource/how-to-add-keyframes-in-capcut). JoyMedia's timeline is for review and frame navigation; it does not expose the production team's full editing controls to clients or reviewers.

## Storyboard review

The guided storyboard shows ordered image panels, scene numbers, durations, short captions and image-review status. Four columns fit desktop screens, two or three fit tablets, and phones show one. Images use `object-fit: contain` so reviewers can see the complete composition. A direct storyboard shortcut sits above the main preview.

Selecting a panel opens a larger scene inspector with Previous/Next navigation and the same approval, redraw and video-review actions. Full directions and physical checks stay under Details. Captions are bounded excerpts of the original text; no authored direction, review check or saved approval is rewritten. Missing, stale and approved images keep distinct labels. Image approval follows the existing per-scene controls and permissions.

Presentation reference: [Story2Board](https://github.com/DavidDinkevich/Story2Board), particularly its ordered panels and panel-level prompts. Its README and `main.py` were inspected for this change. UI components remain independent of generation-model bindings.

Live verification uses the seven saved Shera scenes through `uitest@example.com`, including large-image inspection, navigation, full logic checks, focus restoration, mobile layout and opening video review from a panel. Regression checks cover individual approval, archived access, history and timeline comments. Evidence is saved under `/workspace/development/verification/storyboard-review`.

## Inline review and next-version corrections

The client preview now embeds the version-bound review surface itself, with a single player, frame controls, timeline and comments. A history review opens that version in the same preview. Closed reports are filtered on the server before pagination, while explicit links can still restore an authorized closed record. The client can show closed comments with a checkbox. Opening comments does not queue jobs. When scene footage is stale, the preview offers **Update scenes**; a re-export alone is no longer described as fixing changed footage.

The next Shera working edit is `PRJ-02535`, output `ASTV-04185`: a 30-second, 720-frame, 720×1280, 24 fps review cut with stereo AAC audio. Shot 4 is a separate five-second actor-free illustration of one sheet with four bonded constituent plies. Shot 7 uses prepared transparent source artwork on a shared studio ground. The former cut remains in history. Actor shots 1, 2, 3, 5 and 6 reuse earlier footage and still require regeneration; the current edit and open feedback make this limitation explicit. No new ComfyUI video jobs succeeded or were claimed. The configured tunnel refused connections during this revision.

A full correction strategy, source hashes, rendered scene evidence and verified output are retained in `/workspace/development/verification/shera-next-version/`. The layer renderer is count-driven and language-aware; the shared-ground layout accepts dimensions, relative scales and transparent artwork, without case or model branches.
