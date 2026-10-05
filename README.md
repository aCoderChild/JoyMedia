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
cd joymedia
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
# JoyMedia

JoyMedia is an internal product-video workspace. Administrators invite staff
accounts and grant the `JoyMedia User` role; self-registration is disabled by
default. To enable the custom signup flow intentionally, set
`joymedia_allow_signup = 1` in the site configuration.

### Render worker

Export finishing and "Finish film" run for up to an hour on the GPU. Give them
their own worker so they never hold the worker that starts generation runs:

```bash
bench set-config -g workers '{"joymedia_render": {"timeout": 10800}}' --parse
bench worker --queue joymedia_render          # dedicated render worker
bench worker --queue short,default,long       # everything else
```

Without a `joymedia_render` worker these jobs fall back to the `long` queue.
