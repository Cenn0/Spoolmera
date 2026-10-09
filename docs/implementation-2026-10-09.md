# Review implementation — 0.10.0

Date: 2026-10-09. This document records the implementation of the architecture, code and functionality review, including all four selected feature increments. It retains Python/FastAPI, Angular, SQLite, Apache-2.0 and the single-container default. The README's AI-developed / human-engineered disclosure is preserved.

## Starting point and delivery

PR [#7](https://github.com/Cenn0/FilamentManager/pull/7), head `95738baea12d7fa63040c57e1ade492f28f30be9`, was merged on the user's instruction. The implementation starts from the resulting main commit `53eaf91533834441554dc66a4eaa7dae938b7a1b` and continues in [PR #8](https://github.com/Cenn0/FilamentManager/pull/8). The first migration fix is separately reviewable at commit `c431892af74616930300ef142cb4a46c225ab321`.

Repository visibility and public release publication are separate decisions. This work prepares versioned, checksum-protected CI test artifacts; it does not publish a public release.

## Completed plan

| Work package | Delivered behavior | Primary validation |
| --- | --- | --- |
| AP0: execution baseline | Isolated continuation; official Angular unit-test builder with Vitest/jsdom; original browser gate retained and extended | Focused Angular regressions and the existing five CI jobs |
| AP1: migrations/material identity | Version-gated upgrade; legacy mapping only when no material rows exist; canonical 1–8 explicit assignments including single T3; historical inconsistency diagnostics | `test_migration_invariants.py`, material mapping and browser cases |
| AP2: stock/accounting | Stock revisions; stale-measurement rejection; actual/partial/zero use; idempotent decisions; linked compensation; explicit reconciliation after an intervening weighing | 29 cases in `test_accounting_reconciliation.py`, existing scale/material suites |
| AP3: physical operation coordination | Durable per-printer start/upload exclusion; fresh enabled/stock/archive/mapping checks; restart-persistent unknown outcomes; terminal/explicit release; endpoint binding | 26 cases in `test_printer_operation_coordination.py` |
| AP4: complete UI workflows | Immutable previews; out-of-order response protection; explicit tool/slot UI; purchase fields can be cleared; route/focus refresh; role-aware deep links | 46 frontend tests, real browser smoke |
| AP5: recoverability | WAL-aware bounded backups; supported-schema validation; corrupt-byte retention; atomic offline restore; UID/mode preservation; exclusion of a live API | Recovery tests and `container_restore_smoke.py` |
| AP6: supervised operations | Validated startup settings; kernel ownership plus short renewable polling lease; readiness; diagnostics; isolated notifier credentials and recovery epoch | Poller/diagnostics/notifier suites and notifier container smoke |
| AP7: contracts/builds | Generated request/response types for changed features; drift check; hash-locked Python graph; npm lock; pinned image inputs; aligned version | Clean hash-verified installation, generator check, frontend build and dependency audits |
| AP8: useful increments | Full history/archive; atomic batch rolls and both label sizes; product restock targets; targeted optional notifications | Inventory API, frontend and browser workflows; authenticated notifier delivery fixture |
| AP9: release/operations | Architecture, recovery, update and feature documentation; hardware limits; actual STL fixture; versioned test image with metadata/checksums | Default image/launcher, recovery, notifier and real slicer CI paths |

All twelve review findings R01–R12 have corresponding implementation and regression coverage. No finding is silently reclassified as hardware support or deferred infrastructure work. Suspicious historical stock data is surfaced for explicit review; the migration does not invent corrective inventory entries.

## Important behavioral decisions

### Consumption is separate from physical tracking

A failed 200 g estimate can be reviewed as 37 g actual use, explicit zero, or the original estimate. Each review retains the estimate and previous ledger entries. Correcting a previous 200 g posting to 37 g normally adds a linked +163 g compensation. A later completion observation cannot debit the already reviewed amount again.

Absolute weighing is not automatic job attribution. If consumption is still unresolved, the operator reconciles the job and measurement together. Scale receipts carry their original revision and tare; stale receipts receive a conflict.

The final review found and covered a further ordering case: estimate posted, stock weighed, then estimate corrected. In that case the correction requires a fresh measurement. The service records both the job compensation and a separate measurement reconciliation, leaving the confirmed physical balance correct while the job reports its actual use. Shared operation links keep both entries visible in job history; measurement reconciliation is excluded from print-cost totals.

### Uncertain printer outcomes stay visible

A successful HTTP response acknowledges a request. It is not proof that a physical print completed. An uncertain start/upload blocks further conflicting operations on that printer and survives restart. Confirmed historical commands retain a release marker so the next legitimate job can proceed.

Cancellation or Stop tracking does not itself prove that a physical operation ended. Administrators can release an operation after checking the actual printer and recording a reason. Accounting decisions never implicitly clear a physical-operation fence. Ordinary CI replaces printer transports; it does not run physical commands.

### Planning remains advisory

A loaded slot records the roll the operator says is loaded. Reservations reduce displayed unreserved availability but do not move or consume filament. Restock suggestions use product target minus active physical stock, with reserved and available quantities separately shown. Products without active rolls still appear. There is no automatic supplier order or automatic print start.

### Recovery preserves uncertainty and resets access

Restore is an offline operation. The application lock blocks replacement while an API is running, including when its poller has failed. A validated candidate replaces the database atomically; damaged prior files and relevant sidecars are retained. Runtime UID/GID and mode are preserved, including newly created lockfiles.

Restored browser sessions and machine tokens are revoked, and the notification instance epoch changes. Operators log in and reissue integration tokens. Existing uncertain printer operations remain uncertain. This avoids trusting a restored old credential/cursor snapshot as if no rollback had occurred.

## Verification evidence

The complete backend suite was run in a fresh CPython 3.12 environment installed from the new lockfiles using `--require-hashes`: **221 passed, 2 skipped**. The two skipped checks require mapping UID 10001, which this local execution host does not support; the actual Docker recovery gate verifies that boundary on the container platform. A Starlette warning about the existing httpx test adapter remains; it is not a failed test.

Frontend verification: **46 tests across 12 files passed**, TypeScript checking passed, and the production Angular build passed without Angular warnings. Generated API contracts match their Pydantic sources. The existing test helpers for multiple user sessions now share a running application instead of accidentally starting a second application lifespan.

The [current PR checks](https://github.com/Cenn0/FilamentManager/pull/8/checks) provide the required commit-specific remote evidence:

| CI job | What it actually exercises |
| --- | --- |
| `test` | Hash-verified dependency install, backend compile, generated contracts, Angular typecheck/unit tests/build, API regression suite |
| `docker-smoke` | Hardened default image, HTTP workflows, restart persistence, isolated launcher, root-assisted offline restore followed by runtime writes/backup, lost/corrupt target recovery, notifier image and credential isolation; test artifact packaging |
| `browser-smoke` | Fresh admin setup, inventory, QR/CSV, archive/reactivation, batch labels, restock/history, T3/T0 slot mapping, signed synthetic failure followed by 37 g use and 40 g correction, roles/deep links, password/session revocation, mobile view |
| `slicer-build` | Optional overlay build/network/token isolation and an actual closed-cube STL through API → isolated PrusaSlicer → G-code download |
| `security-audit` | Locked Python runtime and npm runtime dependency audit gates |

Docker and a real browser are not available in the local execution host. Its browser-download endpoint returned HTML rather than an executable archive, so local compilation/component tests are not represented as browser validation. Remote gate results must be read at the tested PR commit. Browser failures retain a trace, screenshot and server log for diagnosis.

## Supported and unverified behavior

| Capability | Implementation/testing boundary | Physical validation |
| --- | --- | --- |
| Inventory, accounting, roles, import/export, archive, labels, restock | Application API and UI tests | No printer needed |
| Moonraker history and control | Documented adapter; transport/state regressions; control remains opt-in | No printer or firmware version certified |
| OctoPrint | Adapter polling/upload/control contracts; completion remains manual-review-only | No printer or firmware version certified |
| PrusaSlicer | Pinned optional Debian package; real tiny STL conversion gate | No generated G-code printed on hardware |
| Signed cloud/scale relay | HMAC, replay/context validation and explicit review | No vendor cloud, sensor calibration or ESP32 firmware certified |
| NFC/OpenPrintTag identifiers | Identifier lookup and optional browser reader path | No universal NFC or NDEF decoder claim |
| Backup/restore and notifier | API/process tests plus real container gates | Additional architectures require their own validation |

Native vendor-cloud login, OIDC/SSO, mid-job spool replacement accounting, automatic print queues/purchasing, full production costing and universal NFC support remain deliberately outside the selected plan. The default application still needs no broker, external database or paid service.

For supported commands and operating limits, read [Operations](operations.md), [Testing](testing.md), [Architecture](architecture.md) and [Build inputs](build-reproducibility.md).
