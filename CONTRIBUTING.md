# Contributing

Spoolmera is a **free, open-source, Apache-2.0** project and an explicit experiment in AI-led development with human engineering oversight. Contributions, tests, review, documentation and design suggestions are welcome. No paid APIs, SaaS account or paid plugin is required.

## Guidelines

1. Open an issue or a small pull request describing a user-visible benefit or correctness bug. Prefer incremental changes to sweeping infrastructure refactors.
2. Keep Angular features under `frontend/src/app/features/` and Python behavior in the appropriate `app/api/`, `app/services/` or `app/infrastructure/` module.
3. Never introduce silently repeated physical printer commands, invented completion evidence, unaudited stock subtraction, remote arbitrary executable paths or unallowlisted device connections.
4. Add backend regression tests for state changes, access control, migrations and edge cases. If an external device is involved, describe what was hardware-tested versus mocked.
5. Run `python scripts/check_docs.py`, `python -m pytest -q`, `python scripts/generate_api_types.py --check` and `cd frontend && npm ci && npm run typecheck && npm run build`. Use the repository's CI for Docker and browser checks.
6. Do not commit secrets, databases, private printer profiles or generated build directories.
7. Keep code comments, documentation and UI source messages in English. Supply German translations for user-facing messages and run the translation check. Keep the existing Apache 2.0 license headers where applicable; third-party licenses must be respected.
8. Update the [documentation index](docs/README.md), README and feature/status matrix when behavior changes. Screenshots must originate from the real Angular browser CI using disposable fixture data; record the revision and workflow run in [the screenshot provenance guide](docs/screenshots/README.md). Do not replace actual UI captures with generated mockups.

No contributor is required to use an AI tool. AI-generated patches receive the same review, tests and security scrutiny as any other code. Maintainers remain accountable for the final design and merged changes.

## Pull requests and public repository trust

Use a feature branch and open a pull request to `main`; do not push directly to the default branch. All five CI jobs must pass before merge once the [branch ruleset](docs/repository-security.md) has been activated by an administrator. The project currently has a single maintainer, so required third-party approval is not configured; self-review is not an independent security assessment.

The CI workflow runs contributed code with a read-only GitHub token and no production secrets. Test Docker images are published as GitHub Actions artifacts only from `main`, after merge and the required checks. Do not ask maintainers to run PR-supplied scripts with elevated access or to execute binary artifacts from an untrusted fork. Review [the security reporting policy](SECURITY.md) before disclosing a vulnerability.

Dependabot changes are normal pull requests, not automatically trusted updates. Python hashed dependency locks and pinned Docker image digests need manual synchronization per [build reproducibility](docs/build-reproducibility.md).
