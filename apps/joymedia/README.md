### JoyMedia

AI Video Generation for product commercialization

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app joymedia
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/joymedia
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Builds the JoyMedia frontend and runs the Frappe test suite on pushes to `main` and pull requests.

## Frontend

The customer portal is a Vue application built with the official `frappe-ui` package.

From `joymedia/frontend`:

```bash
npm ci
npm run build
```

After building, link the app assets in a bench with:

```bash
bench build --app joymedia
```

The portal is available at `/joymedia/campaigns`.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
