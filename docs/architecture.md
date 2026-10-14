# JoyMedia architecture

## Why `joymedia/joymedia` exists

Frappe separates an application package from its Desk module. In JoyMedia:

| Location | Responsibility | Typical import |
| --- | --- | --- |
| `joymedia/` | App code, hooks, APIs, background services, frontend assets | `joymedia.services.*` |
| `joymedia/joymedia/` | Frappe module named `JoyMedia`: DocTypes, reports, workspace | `joymedia.joymedia.doctype.*` |

The module name is persisted in Frappe records and migrations. Treat the inner
directory as framework-owned structure. New business logic belongs in an API,
service, or adapter; new persisted Frappe objects belong in the module.

## Code boundaries

```
Browser (joymedia/frontend)
        │
        ▼
API endpoints (joymedia/api)           thin: permissions + delegate
        │
        ├── Services (joymedia/services)           application logic, see the map below
        ├── Workflow adapters (joymedia/workflow_adapters)   ComfyUI graph execution contracts
        │
        ▼
Frappe DocTypes and reports (joymedia/joymedia)
        │
        ▼
External language model, ComfyUI (FLUX, H3, MMAudio) on a separate GPU host
```

Keep API endpoints thin: validate permissions and delegate work to a service.
Services own application behavior and must not depend on Vue components.
Adapters translate validated workflow contracts to provider-specific requests.
DocType controllers enforce data invariants and preserve Frappe lifecycle
behavior.

## Services map (`joymedia/services/`)

One package per concern; every package and module opens with a docstring saying what it is for. Nothing in
`services/` is a test.

| Package | Purpose | Modules |
| --- | --- | --- |
| `intake/` | Bring a client's material in | `project` (create a project from a sheet/brief/pictures, readiness checklist, PDF picture extraction), `assets` (Media Assets), `vision` (describe pictures), `image_manifest` |
| `planning/` | Story → scenes → prompts | `workbook` (xlsx import), `production` (Follow the sheet / Creative planner), `prompts` (what each workflow receives), `llm` (language-model client), `revisions` (AI edits), `video_plan` (brief → plan), `film_director` (story-film rules), `durations`, `signature` (approval), `jobs` (background planning), `quality_feedback` |
| `keyframes/` | First-frame stage | `stage` (draw, review, approve each scene's frame), `overlay` (paste real logo/product/mascot, character boards, layout), `reference_board` |
| `generation/` | Render life cycle | `orchestrator` (runs, tasks, retries), `runner` (stage inputs, submit), `ingestor` (collect results), `segments`, `artifacts`, `takes` (regenerate/switch), `failures` |
| `workflows/` | ComfyUI and workflow records | `comfyui` (HTTP client), `resolver` (task → graph), `routing`, `profiles`, `pipeline` (promoted pipeline) |
| `editing/` | After generation | `timeline` (clips, trims), `export` (timeline → film), `composer` (assemble scene segments), `post_production`, `finishing` (upscale, 60 fps) |
| `audio/` | Sound | `plan` (cues, effect layers, per-scene screen), `check` (effects vs music/voice) |
| `review/` | Quality gate | `authority` (human approval), `visual_quality` (automated QA) |
| `project/` | Shared plumbing | `context` (snapshots), `realtime` (socket events), `preferences`, `tuning` (every tunable number), `modes`, `render_queue` |

Dependencies point down this list: `intake`/`planning` use `project`, `generation` uses `workflows` and `keyframes`,
`editing` uses `generation` results and `audio`. Tests live in `joymedia/tests/<package>/`, mirroring this tree;
`tests/support/` holds fixtures and the keyframe regression cases that need a real ComfyUI.

Guard tests keep the structure honest: `tests/test_frontend_api_contract.py` (every server method the studio
calls exists and is whitelisted) and `tests/test_hooks_contract.py` (every function `hooks.py` names exists).

## Main production flow

1. Assets are stored as immutable Asset Versions.
2. The AI director creates a shot plan and route selection validates its real
   workflow input contract.
3. The orchestrator creates immutable generation attempts and submits work to
   ComfyUI.
4. Generated outputs become selected takes and receive asynchronous automated
   visual QA. Human approval remains the delivery gate.
5. Approved active shots can enter post-production or timeline export.
6. Reviews and attempts feed analytics and the quality-feedback service for
   later planning and routing decisions.

## Safe structural changes

- Keep repository-level package metadata (`pyproject.toml`) at the root.
- Keep the outer `joymedia` package and inner `joymedia` Frappe module intact.
- Do not commit Bench runtime directories such as `apps/`, `sites/`, `env/`,
  `logs/`, or generated frontend dependencies.
- Run `python scripts/verify_app_layout.py` and `python scripts/run_tests.py <site>` after
  changes that affect imports, hooks, DocTypes, or package layout.
