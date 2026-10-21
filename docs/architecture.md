# JoyMedia architecture

JoyMedia is a Frappe app. The browser edits project data; server services freeze a
production plan; workflow adapters submit it to ComfyUI; immutable attempts and
asset versions record the result. A review export and an approved release are
separate outputs.

## Package boundaries

| Location | Responsibility |
| --- | --- |
| `joymedia/frontend/src/pages` | Route composition and editor layout |
| `joymedia/frontend/src/composables` | Workspace, generation, timeline, import and finishing state |
| `joymedia/frontend/src/components` | Reusable views and editor controls |
| `joymedia/api` | Authenticated editor operations and orchestration entry points |
| `joymedia/services/intake` | Workbook and reference import, project readiness |
| `joymedia/services/planning` | Workbook interpretation, scene planning and prompt compilation |
| `joymedia/services/scene` | Provider-independent identities, references, physical contracts and evidence |
| `joymedia/services/keyframes` | Location anchors, opening frames, source-art repair and approval |
| `joymedia/services/generation` | Frozen runs, task dependencies, submission, retries and result ingestion |
| `joymedia/services/workflows` | Workflow capabilities, routing, graph binding and ComfyUI transport |
| `joymedia/workflow_adapters` | Provider serialization and versioned execution graphs |
| `joymedia/services/editing` | Timeline assembly, finishing and export |
| `joymedia/services/audio` | Voice, effects, audio planning and checks |
| `joymedia/services/review` | Sampled visual admission, brand review, comments and release checks |
| `joymedia/services/consistency` | Source-art preservation, tracking and surface repair |
| `joymedia/services/project` | Snapshots, edit versions, selected references and realtime updates |
| `joymedia/services/runtime` | Configured service endpoints |
| `joymedia/joymedia` | Framework-owned DocTypes, reports and workspace |
| `deploy` | GPU setup, pinned upstream provenance and operating tools |
| `scripts` | Repository checks and repeatable verification tools |

The outer `joymedia` directory is the Python app; the inner directory is Frappe's
persisted `JoyMedia` module. Flattening these would break installed-site metadata.
Services belong outside DocType controllers unless they enforce a persisted invariant.

## Production flow

1. Import the workbook and select immutable reference views. The workbook owns
   the scene order, duration, action and claims. Brand style describes visual
   qualities; scene rows own their actors, locations and props.
2. Plan and approve scenes. `planning/production.py` coordinates planning;
   `language_rules.py` contains pure translation-fidelity and vocabulary rules.
   `scene/contract.py` holds physical relationships and timed checks.
3. Compile a prompt from that plan. `planning/camera.py` chooses one camera
   behavior from structural data; `planning/h3.py` serializes H3 fields.
   Provider-specific serialization does not choose the advertised product or case.
4. Resolve declared workflow capabilities and input roles. Freeze inputs, prompt,
   policy and workflow versions before submitting a generation attempt.
5. Ingest artifacts and run sampled visual checks. Failed or uncertain evidence
   cannot establish product fidelity. Inspect the actual footage before selecting
   a reviewed take; preserve prior selected takes when rejecting a candidate.
6. A declared static product/camera contract can use the existing source-frame
   presentation route. Exact source artwork and composition mode are separate:
   source preservation must not turn an authored staged packshot into a white
   catalogue-photo card. Closing holds follow the actual frozen image dependency.
7. Assemble selected takes, narration, effects, music and editorial graphics into
   the timeline. Export a review version; release checks remain a separate gate.

## Automatic product-reference production

The New video dialog can accept product/mascot pictures without a written story.
`api/creative.py` freezes the requested references, optional direction, inherited
or explicit duration/geometry, variant count and auto-render authorization in a
`Creative Batch`. Photo count never selects scene or video count. Reference
identity keys group alternative views of one product or actor.

`planning/creative.py` uses the configured planner and a persisted variation nonce
to write distinct, timed scripts. Prior variant loglines guide variety. Approved
claims and reference descriptions constrain the creative brief. Missing geometry
or duration is proposed by the script and recorded with a format rationale;
an explicit input always wins. There is no automatic reel-format substitution.

The writer fills the existing downloadable JoyMedia workbook template. The normal
workbook importer and timed production planner then create shots, reference
bindings, scene contracts and camera intents. No parallel video renderer or
provider-specific creative path exists. Every variant exposes its generated XLSX.

The existing keyframe stage, ComfyUI Runs/Tasks/Attempts, admission checks,
generation and finishing jobs remain authoritative. The batch scheduler advances
each variant independently and uses short locks only for state transitions.
Variant-level merges prevent planning/polling from erasing one another's results.
Planning yields the long worker between variants. Cancellation is durable before
native job interruption; uncertain or failed evidence becomes Needs Attention,
never an invented pass or a falsely reviewed take. Completed means review export,
not automatic release qualification. Music follows the generated script brief.

Reference action analysis reuses Apache-2.0 OpenStoryline's clip-understanding
prompt and its JSON parser; pinned source paths, hashes and license are under
`joymedia/vendor/open_storyline`. CameraPath Lab supplies PTS probing and decoding.
Short chronological windows preserve contact and consequences that whole-shot
captions missed. These are sampled observations, not cut boundaries or verified
product claims. Sampling lives in `workflow_adapters/graphs/action_reference_sampling.json`.

Reviewed upstreams: FireRed-OpenStoryline at
`c9e945215586f45c12a61c1951ee9a8e9c43a027` is integrated through existing vision
and planning clients. DigitalMarketingAgent at
`3b73c805a648df8d925901fd213c559504c6eb93` informed the photo-to-storyboard review;
its fixed render settings and Wan/interpolation backend were not adopted.

## Finishing responsibilities

`editing/post_production.py` keeps the stable whitelisted endpoints and queued job
entry points. Its focused collaborators are:

- `music.py`: music briefs, score rendering, soundtrack placement and reuse.
- `bridges.py`: optional generated transition clips and overlap bookkeeping.
- `rendering.py`: workflow execution, frame extraction and persisted output assets.
- `queries.py`: shared take and asset-version lookups.

The facade re-exports existing helper names for callers. New code and tests should
import the module that owns the behavior. Mock a collaborator where the caller
looks it up, rather than relying on an old facade alias.

The editor follows the same boundary: `ProjectStudio.vue` composes the workspace;
`useStoryboardImport` owns upload/sheet selection, `useProjectFinishing` owns
finishing commands and polling, and `utils/download.js` handles session-authenticated
downloads. Timer cleanup belongs to the composable that creates the timer.

Computed composition bytes are promoted through `runtime/transactions.persist_result`.
Only the short database/file promotion is retried; inference, normalization and
visual QA run once. Promotion rechecks cancellation and reuses the immutable
attempt output. A late finishing worker cannot revive a cancelled job.

## Change and deployment rules

- Keep case-specific artwork, wording and action in workbooks and reference data.
  Keep node IDs and model options in versioned workflow contracts.
- Reuse upstream workflows and installed capabilities before adding dependencies.
  Record repository revision, model identity and license under `deploy`/`docs`.
- Do not edit admission implementation files while frozen runs are active. Those
  runs verify an implementation digest; finish or cancel them before deployment.
- Preserve whitelisted HTTP paths, RQ entry points, DocType names and migration
  history during internal refactors. Introduce schema changes through migrations.
- Keep weights, private media, sessions, site configuration, logs and build
  dependencies outside Git. Generated media and database edit history stay in Frappe.

## Verification

From the app checkout, run `python scripts/verify_app_layout.py`,
`ruff check joymedia scripts deploy`, and `ruff format --check joymedia scripts deploy`.
From the Bench, run `python apps/joymedia/scripts/run_tests.py <site>`; this includes
service tests that `bench run-tests --app joymedia` misses. Build the frontend with
`npm ci && npm run build` in `joymedia/frontend` and run the relevant Playwright
checks. Live tests require an explicitly configured authorized session and project.

For an isolated worktree, verify `joymedia.__file__` before testing: running Python
from the live checkout can otherwise import the live app instead of the refactor.
Use `PYTHONSAFEPATH=1` and an explicit `PYTHONPATH`, with the Bench as working directory.

Historical qualification reports under `docs` describe their recorded runs. They
are evidence of those runs, not the current model inventory or release status.

The automatic script writer calls the `writer` capability, independently of the
per-shot production `planner`. Configure `joymedia_writer` for a general
instruction endpoint; absent an override, it inherits the existing translator
endpoint, then planner. No vendor or model name is selected in application code.
Scripts use the existing runtime structured-output transport with a dynamic JSON
schema for the supplied reference keys, format and camera enums. The ordinary
validator still rejects invalid durations, action intervals and unknown cast.

Before importing an automatic script, the writer performs a separate bounded
compliance pass over every scene's action, causal handoff and pacing. This can
reject camera-only prose, missing acquisition/contact phases and disproportionate
holds; it does not certify the physics of a future render. Rejected scripts are
rewritten through the same schema before any keyframe job is admitted.
Native generation and finishing admission is committed inside the batch lock,
so cancellation can observe and stop a newly admitted job before releasing control.

Automatic batch requests also freeze unresolved owner feedback from the project
family and current source-scene comments. The script writer and action editor see
those findings alongside reference keep rules. Historical scene numbers are
context, not a fixed script; copying a finding never marks it resolved.

The current working edit changes automatically only when the requested review
export is ready (or the script is ready in scripts-only mode). Failed or cancelled
planning/rendering does not replace the viewer's currently selected video.
