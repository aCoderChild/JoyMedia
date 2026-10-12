# JoyMedia

JoyMedia is a Frappe application for planning, generating, reviewing, and
finishing product videos with Qwen and ComfyUI.

## Install from a fresh clone

JoyMedia is an app, not a standalone web server. A fresh clone runs inside a
[Frappe Bench](https://github.com/frappe/bench). The following installs the
same repository layout used by CI:

```bash
bench init --frappe-branch version-16 joymedia-bench
cd joymedia-bench
bench get-app https://github.com/aCoderChild/JoyMedia.git --branch main
bench new-site joymedia.localhost
bench --site joymedia.localhost install-app joymedia
bench build
bench start
```

For a direct clone, validate the checkout before adding it to a Bench:

```bash
git clone https://github.com/aCoderChild/JoyMedia.git
cd JoyMedia
python scripts/verify_app_layout.py
```

The app does not include model weights, Qwen, or ComfyUI. Configure those
services separately after installation; see [operations](docs/operations.md).

## Repository layout

```
.
├── joymedia/                 # Python application package
│   ├── api/                  # Whitelisted HTTP endpoints
│   ├── services/             # Generation, QA, routing, and finishing logic
│   ├── workflow_adapters/    # ComfyUI workflow adapters
│   ├── frontend/             # Vue application
│   ├── hooks.py              # Frappe lifecycle and route hooks
│   └── joymedia/             # Frappe module named "JoyMedia"
│       ├── doctype/          # Database schema and server controllers
│       ├── report/           # Analytics reports
│       └── workspace/        # Desk workspace definition
├── deploy/                   # Optional GPU tunnel and systemd units
├── docs/                     # Architecture and operational documentation
├── scripts/                  # Repository validation utilities
└── pyproject.toml            # App package metadata
```

The two `joymedia` directories are deliberate Frappe structure, not duplicate
source trees. The outer directory is the installable Python app. The inner
directory is the Frappe module whose canonical import path is
`joymedia.joymedia`; it owns the app's DocTypes, reports, and workspace.
Renaming or flattening it would break installed-site metadata and migrations.

When working inside a Bench, `apps/joymedia` is the Bench-managed checkout of
this repository. It may appear as a symlink in local development environments;
it is not another source copy and must not be committed.

See [architecture](docs/architecture.md) for boundaries and request flow.

## Development and verification

```bash
python scripts/verify_app_layout.py
bench --site joymedia.localhost run-tests --app joymedia
cd joymedia/frontend && npm ci && npm run build
```

The site name is environment-specific. Use the site created by `bench new-site`
in your local Bench.

## Contributing

```bash
pre-commit install
```

Pre-commit runs Ruff, ESLint, Prettier, and pyupgrade. The GitHub Actions
workflow installs this repository through `bench get-app`, installs the app on
a clean test site, runs the server suite, and builds the frontend.

## License

MIT
