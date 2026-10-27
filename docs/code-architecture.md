# JoyMedia code boundaries

JoyMedia is a Frappe application with a Vue/Frappe UI client. Feature logic belongs in
`joymedia/services/<feature>/`; `joymedia/api/` exposes authenticated Frappe methods
and delegates to those services. Existing dotted API paths are public contracts and
must remain stable while internals move.

| Area | Responsibility |
| --- | --- |
| `intake` | Import, classify, and prepare reference media |
| `planning` | Build and validate scripts, poses, product views, and shot plans |
| `keyframes` | Compose and review first frames |
| `generation` | Coordinate jobs, attempts, and output ingestion |
| `workflows` | Map jobs to ComfyUI graphs and available GPU endpoints |
| `audio` | Direction, speech, and audio synthesis |
| `editing` | Timeline operations, audio lanes, previews, and export |
| `review` | Admission, physical checks, and consistency decisions |
| `project` | Project context, versions, access, and lifecycle |

`services/scene` holds provider and framework independent scene contracts. Database
lookup for generated reference lineage lives in `project/reference_lineage.py`.

The frontend lives in `joymedia/frontend/src`: pages load project data, components
render feature views, composables own shared reactive workflows, and utils contain
pure presentation or timeline calculations. The Rio editor is a workspace component
under `components/studio`. Pure Rio asset labels and reference formatting live in
`utils/rioPresentation.js`; lane layout and timeline math live in
`utils/rioTimeline.js`.

Keep database writes and permission checks in service/API operations. Pure geometry,
timing, naming, and selection functions can be tested without a Frappe site. For
timeline edits, source video and independent audio have separate rules; audio track
placement lives in `services/editing/audio_lanes.py`, while `timeline.py` retains
the stable API functions and transaction boundary.

Before merging a cross-feature change, run the app layout check, Ruff, frontend unit
tests/build, and the Frappe suite. Test the affected live Frappe and ComfyUI path when
the change alters orchestration or rendered output.
