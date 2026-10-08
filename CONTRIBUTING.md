# Contributing

Filament Manager is a **free, open-source, Apache-2.0** project and an explicit experiment in AI-led development with human engineering oversight. Contributions, tests, review, documentation and design suggestions are welcome. No paid APIs, SaaS account or paid plugin is required.

## Guidelines

1. Open an issue or a small pull request describing a user-visible benefit or correctness bug. Prefer incremental changes to sweeping infrastructure refactors.
2. Keep Angular features under `frontend/src/app/features/` and Python behavior in the appropriate `app/api/`, `app/services/` or `app/infrastructure/` module.
3. Never introduce silently repeated physical printer commands, invented completion evidence, unaudited stock subtraction, remote arbitrary executable paths or unallowlisted device connections.
4. Add backend regression tests for state changes, access control, migrations and edge cases. If an external device is involved, describe what was hardware-tested versus mocked.
5. Run `python -m pytest -q`, `python scripts/generate_api_types.py --check` and `cd frontend && npm ci && npm run typecheck && npm run build`. Use the repository's CI for Docker and browser checks.
6. Do not commit secrets, databases, private printer profiles or generated build directories.
7. Keep user-facing UI, code comments and documentation in English. Keep the existing Apache 2.0 license headers where applicable; third-party licenses must be respected.

No contributor is required to use an AI tool. AI-generated patches receive the same review, tests and security scrutiny as any other code. Maintainers remain accountable for the final design and merged changes.
