# Filament Manager architecture (v0.6)

This project is **free and open source (Apache-2.0)**, a deliberately small, AI-developed and human-engineered self-hosted application, not a commercial SaaS product. Aim for understandable contributions and safe default behavior rather than elaborate infrastructure.

## Deployment and boundaries

- **Normal mode:** one non-root read-only API Docker container, Angular static build, SQLite WAL database in a persistent volume; loopback port by default.
- **Optional slicing mode:** another container on an internal-only Docker network, with its own token, CPU/RAM/PID limits, no printer keys, no SQLite volume and no published port. The worker produces downloadable G-code; the API never directly runs PrusaSlicer.
- **External devices:** Moonraker and OctoPrint HTTP adapters use exact private IP allowlists, no DNS hostnames, no redirects/proxies, bounded requests and operator-provided environment secrets. No native proprietary cloud integration is promised.

## Code organization

`app/api` presents FastAPI APIRouter modules and Pydantic response contracts. `app/core/policies.py` grants explicit editor/admin permissions per route instead of inferring permissions from URL prefixes. Global session/CSRF/Origin enforcement remains in `app/auth.py`. `app/services` implements inventory queries, ledger rules, command coordination, poller leases and diagnostics. `app/infrastructure/printers` normalizes controller observations and declares capabilities. `app/infrastructure/database/migrations.py` contains the idempotent legacy v2–v4 upgrade, schema v5 additions and separate restart recovery without destructive renames. Angular features live in `frontend/src/app/features` and are lazily loaded; backend response models generate the checked TypeScript declarations in `core/api/generated-contracts.ts`.

**Dependencies:** HTTP layer → service layer → database and device ports. The shared accounting service is the only intended place to debit physical material, whether an event starts in a route or a controller observation. No broker or external database is required for this single-host application.

## Persistent entities

| Table | Purpose |
| --- | --- |
| products / spools | Filament catalogue and physical UUID-identified rolls |
| movements | Append-only stock movement ledger; v5 source and actor fields |
| print_jobs / job_materials | Registered jobs and explicit tool-to-spool estimates |
| print_runs | Observed controller run IDs and states |
| printer_commands | Durable physical intents, acknowledgements and unknown outcomes |
| cloud_event_receipts | Signed relay replay deduplication |
| printer_poll_state / worker_leases | Reconciliation diagnostics and single-owner polling |
| users / auth_sessions / auth_failures / audit_events | Access, session security and accountability |

Balances are integer grams. Multi-tool consumption must be fully applied to all mapped physical spools, or to none. Database UNIQUE constraints prevent duplicate movements for the same job/spool; independent external run IDs prevent accidental file-name matching across repeated prints. CSV exchange is **not** a full database backup.

## Print and command lifecycle

A print registration does not start a machine. An admin must enable controller writes and explicitly upload/start after review. A start intent is inserted as `sending` **before** the HTTP side effect. A successful HTTP response produces `acknowledged`, not `completed`; a lost or failed response produces `unknown`. Polling with an immutable Moonraker run ID can advance a command to `confirmed`, and a previously observed `in_progress` run that becomes `completed` can atomically debit estimated material. Missing evidence, OctoPrint idle, a cloud report, cancellations, stock shortages or ambiguous file matches yield `needs_review`.

Unknown starts are never automatically retried. A human may clear an unconfirmed start only after verifying it did not physically happen and recording an explanation. This is an explicit at-most-one-request safety policy, **not** a guarantee that the controller itself executes exactly once. Do not confuse successful HTTP delivery with proven printer execution.

Job state and material accounting state are stored separately in schema v5. No automatic deduction implies sensor-verified material weighing.

## Migrations and backups

Schema v5 builds on v1–v4 and uses additive columns/tables and constraints. Existing UUIDs, numeric IDs and ledger entries are retained. Forward-only migrations reject newer unknown user_version values; no automatic downgrade is supported. Back up first.

For consistent online backup, use `python scripts/backup.py /path/to/backup.sqlite3 --database /path/to/live.sqlite3` with permission to read the mounted database. The CLI refuses overwrite and verifies `PRAGMA integrity_check`. Restore with the application stopped; exercise restore before relying on backups.

## Extending controllers

Implement a controller-specific adapter conforming to `PrinterAdapter` with capability flags. Never claim a generic OctoPrint idle result verifies a completed print, nor a vendor cloud event verifies material consumption. Preserve controller-native run identities across restarts; always route updates through the accounting service.

## Engineering gates and trust

CI runs Python/Angular compilation, backend regression tests, browser workflows, Docker lifecycle persistence, isolated slicer image build and dependency audits. TypeScript DTOs are regenerated from Pydantic contracts with `python scripts/generate_api_types.py`, and `--check` verifies drift. Hardware tests, malicious-file analysis, penetration testing and disaster recovery exercise remain operator responsibilities.

**Not goals at this stage:** microservices, Kubernetes, paid cloud services, unverified proprietary cloud APIs or tenant isolation. OIDC/SSO is not implemented. SQLite and one API worker remain the supported baseline.
