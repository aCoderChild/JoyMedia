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
API endpoints (joymedia/api)
        │
        ├── Services (joymedia/services)
        │       ├── planning and prompt compilation
        │       ├── workflow routing and orchestration
        │       ├── visual QA and review handling
        │       └── post-production and export
        │
        ├── Workflow adapters (joymedia/workflow_adapters)
        │       └── ComfyUI graph execution contracts
        │
        ▼
Frappe DocTypes and reports (joymedia/joymedia)
        │
        ▼
External Qwen and ComfyUI services
```

Keep API endpoints thin: validate permissions and delegate work to a service.
Services own application behavior and must not depend on Vue components.
Adapters translate validated workflow contracts to provider-specific requests.
DocType controllers enforce data invariants and preserve Frappe lifecycle
behavior.

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
- Run `python scripts/verify_app_layout.py` and the full app test suite after
  changes that affect imports, hooks, DocTypes, or package layout.
