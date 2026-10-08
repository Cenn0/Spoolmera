# Independent regression review — 2026-10-08

Base reviewed: `ce24d1ddb9397b810d277e80aca534ff47ad37e8` on `main`.
This follow-up examines the existing implementation, rather than treating the
previous review or green CI as proof that all edge cases are covered.

## Confirmed findings and fixes

| Priority | Reproduction / consequence | Correction |
| --- | --- | --- |
| High | Two Moonraker runs with the same filename after registration: the previous matcher silently selected the latest run, potentially attaching the wrong physical print to a spool. | Multiple unclaimed candidates require manual review, without automatic association or stock deduction. |
| High | A completed run first seen after completion entered review without storing its external ID. A manually confirmed debit could then be registered against the same history entry again. | Persist external IDs for review states; exclude already claimed runs, backed by the existing database uniqueness constraint. |
| Medium | Admin reset or self-service password change accepted surrounding spaces, while login stripped them. The exact replacement password then failed to authenticate. | Trim usernames only; preserve passwords exactly across setup, account creation, login and changes. |
| Medium | Malformed nested Moonraker/OctoPrint JSON produced uncaught exceptions or misleading successful responses. | Validate response objects, states, filenames and history identities before changing tracking or stock; return HTTP 502 on invalid controller contracts. |
| Medium | OctoPrint folder/fixture.gcode was compared to its basename fixture.gcode and could not be tracked correctly. | Prefer the documented relative file path; fall back to name when path is absent. |
| Medium | Updating a printer to another existing printer's name raised a database uniqueness exception and HTTP 500. | Check name conflicts in the write transaction and return HTTP 409. |
| Low | Non-ASCII CSRF/bootstrap header values caused string compare_digest to throw TypeError. | Compare encoded bytes and reject invalid secrets with HTTP 403. |
| Medium | Revoked/expired sessions left the Angular workspace displayed with repeated authorization failures. | Clear frontend authentication when a protected API responds with HTTP 401; return to login. |
| Low | Fast automated navigation could fill an Angular control before its form registration completed. | Wait for the user form's registered validation state before entering test data. |

The first 31 added regression cases produced **14 failures and 17 passes**
against the unmodified behavior. The fixes made those cases pass, and seven
additional checks cover nested file paths, malformed history identities,
SPA routing and preservation of test-launcher credentials.

## Executed validation

| Check | Local result |
| --- | --- |
| Original API suite | 32 passed before changes |
| Full Python suite after fixes | **70 passed** (38 additional cases) |
| TypeScript typecheck and Angular production compilation | Passed |
| Real Chromium browser workflow against compiled Angular/FastAPI | Passed: setup, inventory, movements, QR, CSV, deep links, roles, password with spaces, session revocation and mobile layout; no page errors |
| HTTP boundary smoke against a running Python server | Passed: UI routes, authentication, ledger, CSV and logout |
| Server stop/start with the same SQLite database | Passed: accounts, remaining stock and movement history persisted |
| Python compilation, workflow shell syntax, YAML parsing | Passed |
| Docker image execution locally | Unavailable: no Docker executable/daemon in the review environment; CI executes the image and isolated Compose launcher |

The installed Starlette TestClient emits a deprecation warning for httpx.
It does not fail the suite; migration of the test transport remains follow-up
maintenance. Local Chromium was supplied separately because the standard
Playwright browser download failed in this environment. CI uses the repository's
pinned Playwright installation and standard Chromium installation step.

## Test delivery

`scripts/start_test.py` prepares a random bootstrap token in `.env.test` and
starts an isolated, loopback-only Compose installation on port 8766. It retains
existing test configuration and uses a project/volume separate from normal use.
There are no default account passwords and no configured printer IPs.

CI now publishes a JUnit report and a downloadable Linux amd64 image package
after container HTTP, restart/persistence and test-launcher checks pass.
Require all jobs in that CI run to be green before relying on the package.
See [testing instructions](testing.md).

## Boundaries and follow-up work

- Controller behavior was tested with documented response fixtures, not real
  devices. Hardware checks remain necessary for firmware/authentication variants,
  outages and cancelled/failed prints.
- Polling reads at most 25 Moonraker history entries. A long outage can leave an
  already associated job unresolved after its entry leaves that window. It must
  not trigger an inferred debit; history lookup by ID/pagination is follow-up work.
- Existing review rows created before the fix may have no external ID. Their
  physical-run identity cannot be reconstructed reliably by a schema migration;
  verify those rows manually before recording consumption.
- Estimated grams are not measured usage. Failed prints, purge/waste and
  multi-material jobs still need manual accounting. Ambiguous mappings deliberately
  require human confirmation.
- All accounts share the same inventory. Roles provide access control, not tenant
  isolation. Use one application worker, as documented for in-process polling.
- No remote deployment server is configured. A downloadable test container is
  provided; this review does not establish an externally reachable live service.

## Support and recommendation classification

- **Works technically:** the executed cases above establish specific behavior and
  regression coverage. Docker execution is established by its separate CI jobs.
- **Documented interfaces:** [Moonraker job history](https://moonraker.readthedocs.io/en/latest/external_api/history/),
  [OctoPrint job operations](https://docs.octoprint.org/en/main/api/job.html) and
  [file metadata](https://docs.octoprint.org/en/main/api/datamodel.html) underpin
  the adapters. This is not manufacturer certification or a universal compatibility claim.
- **Best practice used:** transaction-backed stock/ledger changes, durable run
  identity, explicit controller contracts and regression tests for failed behavior.
- **Security recommendation:** isolated test data, generated bootstrap secrets,
  loopback binding and a trusted HTTPS proxy/VPN for access from other machines.
  Passing tests and this review do not constitute a penetration test.
