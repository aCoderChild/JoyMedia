# JoyMedia

JoyMedia is a Frappe application for planning, generating, reviewing, and
finishing product videos with Qwen and ComfyUI.

## Install from a fresh clone

JoyMedia is an app, not a standalone web server. A fresh clone runs inside a
[Frappe Bench](https://github.com/frappe/bench). For the Python 3.12 and Frappe
15 combination used by the current GPU demo, install MariaDB, Redis, Node.js 20,
Yarn, Git, FFmpeg, Python 3.12 and its development headers first. Follow the
Frappe Bench prerequisites for your operating system. Then, in a development
environment, install the Bench CLI separately from the site's Python environment:

```bash
python3.12 -m venv ~/.venvs/joymedia-bench-cli
~/.venvs/joymedia-bench-cli/bin/pip install 'frappe-bench==5.31.0'
export PATH="$HOME/.venvs/joymedia-bench-cli/bin:$PATH"
bench init --python "$(command -v python3.12)" --frappe-branch version-15 joymedia-bench
cd joymedia-bench
bench get-app --branch main joymedia https://github.com/aCoderChild/JoyMedia.git
./env/bin/pip install --only-binary=opencv-python-headless -e 'apps/joymedia[tracking,cinematography,narration]'
bench new-site joymedia.localhost
bench --site joymedia.localhost install-app joymedia
bench build
cd apps/joymedia/joymedia/frontend
npm ci
npm run build
cd ../../../..
bench start
```

Open `http://joymedia.localhost:8000/joymedia/projects`. The installation above
creates an empty site with its own administrator account. Git does not include
existing demo projects, uploaded files, user credentials, database content, or
server configuration. Add `joymedia.localhost` to your hosts file if your system
does not resolve localhost subdomains.

For a direct clone, validate the checkout before adding it to a Bench:

```bash
git clone https://github.com/aCoderChild/JoyMedia.git
cd JoyMedia
python scripts/verify_app_layout.py
```

The app does not include model weights, Qwen, or ComfyUI. Configure those
services separately after installation; see [operations](docs/operations.md).
Installing the app and opening the UI does not establish that video generation
works. The planner, vision service, ComfyUI, compatible models and workflows,
queues, scheduler and accessible storage must be configured and tested together.
Automatic pose and physical-consistency checks can stop a batch for review; the
current reference-to-final-video flow has not been qualified for every input.

## Repository layout

```
.
├── joymedia/                 # Python application package
│   ├── api/                  # Whitelisted HTTP endpoints
│   ├── services/             # Application logic, one package per concern (see docs/architecture.md)
│   ├── tests/                # All service and adapter tests, mirroring services/
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
# Run from the Bench directory after installing the app and site.
python apps/joymedia/scripts/verify_app_layout.py
bench --site joymedia.localhost set-config allow_tests true
python apps/joymedia/scripts/run_tests.py joymedia.localhost  # optionally add: planning
cd apps/joymedia/joymedia/frontend && node --test tests/*.test.mjs && npm run build
```

The site name is environment-specific. Use the site created by `bench new-site`
in your local Bench. Use a dedicated test site: the test suite can create records and files.
`bench run-tests --app joymedia` only finds the doctype-side tests, so
`scripts/run_tests.py` runs each test module and is what CI uses. To set up a site for rendering,
run `bench --site <site> execute joymedia.install.setup` (see [docs/production-pipeline.md](docs/production-pipeline.md)).

## Contributing

```bash
pre-commit install
```

Pre-commit runs Ruff, ESLint, Prettier, and file-format checks. The GitHub Actions
workflow installs this repository through `bench get-app`, installs the app on
a clean test site, runs the server suite, and builds the frontend.

## License

MIT
