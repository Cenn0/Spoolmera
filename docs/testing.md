# Testing Spoolmera

## Start an isolated test instance

Requires Docker with Compose v2.24 or newer and Python 3.10+ for the launcher.
Docker Desktop must be running on Windows. From the repository root:

```bash
python scripts/start_test.py
```

The launcher generates `.env.test` once, builds the application and waits for
container health. Open **http://127.0.0.1:8766**, copy the bootstrap token from
`.env.test` into the first administrator form and choose your own password
(at least 14 characters). No default administrator credentials exist.

This instance uses the Compose project `spoolmera-test` and its own
`test_data` volume. Your normal instance's data is not used. Ports bind only to
loopback; printer connections are disabled by the empty IP allowlist.
Use `--port 8767` if 8766 is occupied. Avoid starting multiple test instances
against the same volume. Keep the selected port consistent for subsequent starts.

Stop while retaining test data:

```bash
docker compose -p spoolmera-test -f compose.test.yaml down
```

Only when you deliberately want to delete **all test inventory and accounts**:

```bash
docker compose -p spoolmera-test -f compose.test.yaml down -v
```

Existing `.env.test` is never overwritten. If it no longer contains the original
bootstrap token and setup is incomplete, repair that file before starting.

## Download a versioned experimental test image

Regular pull request and `main` CI builds are tested without storing Actions artifacts or caches.
Maintainer-created version tags matching `v<app version>` run the complete CI suite again.
After all gates pass, the tag workflow builds and smoke-tests a fresh Docker image and publishes
a test bundle under [GitHub Releases](https://github.com/Cenn0/Spoolmera/releases).
No bundle exists until a version tag is intentionally published. Release archives are unsigned
experimental testing material, not production- or hardware-certified builds.

Download the `spoolmera-vX.Y.Z-test-linux-amd64.zip` asset and its `SHA256SUMS.txt`,
verify the ZIP using `sha256sum -c SHA256SUMS.txt`, then extract and change directory:

```bash
unzip spoolmera-vX.Y.Z-test-linux-amd64.zip
cd test-release
sha256sum -c SHA256SUMS
docker load -i spoolmera-image.tar.gz
python scripts/start_test.py --prebuilt
```

Open **http://127.0.0.1:8766** and use the token in `.env.test` for first setup.
The tested archive targets Linux amd64, including Docker Desktop with Linux containers
on x86-64 Windows. ARM hosts should build from source; this release workflow does not
validate ARM images. `release.json` records the version, schema, source commit, tag and image ID.
No secrets, databases or pre-created accounts are shipped.

## Suggested manual acceptance checks

1. Create the first administrator; sign out and sign back in.
2. Create a filament and spool, record 125 g of use and check the balance/history.
3. Export CSV, preview/reimport it and verify no duplicate spools appear.
4. Print a QR label and reopen its spool link in the authenticated browser.
5. Create viewer/editor users; verify viewer controls and API access are read-only.
6. Change a password, including spaces; verify the new exact password works.
7. Restart the container and verify accounts, inventory and ledger persist.

For a real printer, use the normal `compose.yaml` and documented allowlist/TLS
setup in `docs/security-and-printers.md`. A hardware test should cover successful,
paused, cancelled and failed prints, disconnection/reconnection and app restart.
The automated controller tests use fake HTTP responses and do not certify devices.

## Run the automated checks

```bash
python -m pip install --require-hashes -r requirements-dev.txt
cd frontend
npm ci --no-audit --no-fund
npm run typecheck
npm run i18n:check
npm test
npm run build
cd ..
python -m pytest -q
```

SPA tests stage their own tiny fixture; application browser tests require the
actual Angular build copied to `app/ui` (as the CI does).
See `.github/workflows/ci.yml` for Chromium installation and server setup.
`scripts/browser_smoke.py` exercises a fresh disposable database and requires
the CI bootstrap token. `scripts/http_smoke.py` also writes test data; never
run either script against an existing user instance.

For the local browser smoke, also export the two synthetic relay settings below
before starting Uvicorn. The shell running `scripts/browser_smoke.py` must use
the same HMAC value. The fresh fixture creates its first printer with ID 1; the
binding authorizes only that printer's test event:

```bash
export SPOOLMERA_CLOUD_HMAC_BROWSER="test-only-browser-relay-secret-long-enough"
export SPOOLMERA_CLOUD_PRINTER_BROWSER="1"
```

The test sends a signed `failed` event to its own API so the partial-consumption
review can be completed in the browser. These values belong only to the
disposable test instance; they are not credentials for a vendor cloud service.

## Verified UI screenshots

The browser CI job creates **real Chromium screenshots from synthetic example data** after exercising the Angular UI in light, dark and mobile layouts. CI validates the captured previews and the complete audit locally, but does not upload them to Actions storage. For durable previews, use the reviewed screenshots committed under `docs/screenshots/`. Five screenshots from the verified [2026-10-10 CI run](https://github.com/Cenn0/Spoolmera/actions/runs/38064112965) are committed under [`docs/screenshots/`](screenshots/README.md) and embedded in the project README, so images remain available after short-lived Actions artifacts expire. The [provenance guide](screenshots/README.md) maps the filenames and explains how to recapture them after frontend changes. They are visual regression evidence, **not** hardware compatibility results or a complete accessibility audit.

### Complete view inventory

The same CI job also runs [`scripts/ui_visual_audit.py`](../scripts/ui_visual_audit.py).
Its default matrix contains **296 distinct captures** in German: 73 desktop
states and 75 mobile states, each in light and dark mode. Desktop captures use
1440 × 1000 pixels; mobile captures use 390 × 844 pixels. The separate browser
smoke checks the inventory and location board at widths from 320 to 1920 pixels.

| Views | Additional captured states |
| --- | --- |
| Overview, spools | Cards, table, locations, scanner, filters, label tray, pending location confirmation, empty results, mobile action menu and navigation drawer |
| Filaments, catalog | Empty search, selected catalog material, product creation and editing, review before adding a catalog product |
| Spool details | Long product names, movement history, consumption, adjustment, weighing and drying dialogs |
| Batch, CSV and Spoolman imports | Input, preview, confirmation and result states |
| History, restock | Empty history filter and all-product restock results |
| Print jobs | Multiple tools, metadata inspection, focus/readiness states, unknown start review, enabled slicer form and all four consumption modes |
| Printers | OctoPrint and Bambu forms, editing, loaded-spool assignment, Bambu status and uncertain upload review |
| Integrations, diagnostics | Token issuance, scale receipts, capabilities and expanded service diagnostics |
| Users, account and authentication | Password reset, account validation, access denied, sign-in errors and first setup |
| Printed labels | 60 × 40 mm, 50 × 30 mm and a batch sheet |

Build and stage the frontend, install the browser dependencies, then run the
audit from the repository root:

```bash
python -m pip install --require-hashes -r requirements-e2e.txt
python -m playwright install chromium
# Run npm ci and npm run build inside frontend first.
mkdir -p app/ui
cp -a frontend/dist/spoolmera/browser/. app/ui/
python scripts/ui_visual_audit.py --serve --strict --output /tmp/spoolmera-visual-audit
```

`--serve` starts the actual backend with a new temporary database, uses normal
API routes to create synthetic inventory and removes the database when finished.
Only the outbound polling cycle is replaced in that test subprocess; production
code and its normal poller lifecycle stay intact. Browser routes block external
requests and physical printer commands. Catalog, hardware and initial-setup
response fixtures are explicitly recorded beside the affected captures.

Open `index.html` for the screenshot gallery and `manifest.json` for the exact
requested state matrix, actual captures, errors and geometry measurements.
The gallery links each preview to its complete screenshot. Focused states also
have viewport captures; full-page images start at the top of the document so
fixed navigation is not displaced by screenshot scrolling. CI validates the complete directory locally but does not upload it. To inspect
full-resolution evidence, run the command above locally; GitHub Actions retains
only the test outcome and logs.

The strict gate rejects missing requested states, capture failures, JavaScript
page errors, horizontal document overflow and concrete regressions such as
overlapping spool titles/statuses, clipped location columns or hidden dialog
close controls. Printed-label checks require a loaded QR image and a visible
product-name line. Intentional internal table scrolling is permitted. Geometry
checks accompany visual inspection; they do not identify every possible design,
accessibility or browser-specific problem.

For a focused rerun, select states by name or glob; `--append` replaces matching
captures and retains the rest of an earlier matrix **from the same build**:

```bash
python scripts/ui_visual_audit.py --serve --strict \
  --contexts mobile-dark --only 'spools-*,locations*' \
  --output /tmp/spoolmera-visual-audit --append
```

Use `--languages en` for English or `--languages de,en` for both supported
languages. A selected-state run checks completeness only for its requested
matrix; consult the manifest before describing it as a complete audit.

## Native Linux arm64 integration gate

The `arm64-container` job runs on GitHub's native `ubuntu-24.04-arm`
runner. It builds the *default* `app-runtime` image for `linux/arm64`,
checks the actual CPU architecture and shipped license notices, runs the
normal login/inventory/CSV HTTP smoke against a disposable loopback-bound
container, restarts the same container to verify persisted ledger data, and
executes the offline restore and UID-ownership harness with a separate
temporary volume. No printer, release image, registry or paid service is used.

A configured job is not automatically evidence of success: check its result
on the exact commit. This gate is a native CI integration test, not a claim
of certified ARM host support or a released `linux/arm64` test bundle. The
optional PrusaSlicer worker and real hardware remain outside this gate.

## Interpretation of results

- **Technically tested:** API roles, password/session handling, import boundaries,
  ledger concurrency and controller state transitions using fixtures; browser and
  Docker execution are reported separately in the review and CI run.
- **Documented upstream interfaces:** Moonraker history/status and OctoPrint job
  responses, including the relative file path. This is not device certification.
- **Recommended test setup:** separate volume, generated bootstrap secret,
  single application worker, unchanged loopback binding.
- **Security recommendation:** use a trusted HTTPS reverse proxy or VPN for
  access beyond the local host. A passing suite is not a penetration test.

## Architecture regression checks

The test suite additionally checks legacy migrations through the current schema, online SQLite backups, durable printer command replay protection, worker token isolation, polling leases, role-restricted API routes, backend/Angular API contracts and stable cursor pagination. CI compiles Python, runs Angular unit tests, builds Angular, verifies generated API models and exercises browser and Docker persistence tests. The opt-in slicer image is built independently from the default runtime.

No automated tests certify a printer model, its firmware or safe physical G-code. Test a real machine while supervised before enabling write controls. The application is free/open source experimental software without a warranty.

The architecture suite also verifies that interrupted physical start commands change to an unknown, non-retryable state on restart and that repeated v5 initializations do not overwrite independent accounting decisions.

## v0.9 additional checks

New regressions cover schema upgrades, material properties, physical scale weighing, drying, spool reservations, per-tool G-code/3MF metadata, imported Spoolman snapshots, token scopes/revocation, tag uniqueness, signed scale receipts and review, cost estimates, label formats, verified online backup and offline restore, and durable notification cursors.

Device tests are mocked: they are **not** evidence of physical NFC/ESP32 compatibility, firmware version certification, native cloud-provider support or a penetration test. Test optional notification Compose with:

    docker compose -f compose.yaml -f compose.notifications.yaml config --quiet

## v0.10 recovery and worker gates

`tests/test_operations_recovery.py` exercises committed WAL growth, logical backup limits, growth while copying, deadline/storage bounds, exclusive backup slots, disconnect cleanup, invalid application backups, altered manifests, corrupt previous bytes, crash sidecars and restored credential/notification-identity reset. An API with a stopped poller must still block offline restore. `tests/test_polling_runtime.py` kills a disposable child process to verify prompt ownership recovery and checks that cancelling an asyncio task does not release a still-running thread's lock. A second application lifespan must fail before migrating an active database. Invalid operator settings must prevent startup.

`tests/test_recovery_preflight.py` uses actual historical table layouts for
schemas 1, 5, 10 and 11 rather than lowering the version number of a current
database. It checks real upgrades, preserved balances/identities/history,
credential handling, uncertain operations, malformed current structures,
manifest errors, source changes and candidate cleanup. `tests/recovery_fixtures.py`
provides the same historical source for the disposable container gate.
`tests/test_verify_backup_cli.py` executes the command in subprocesses and checks
its versioned JSON contract, exit statuses, resource arguments and sanitized
output. These tests prove application/database behavior; they do not certify a
downloaded release package, arbitrary SQL modifications or physical hardware.

`tests/test_notification_bridge.py` verifies quiet initialization, condition-based deduplication, partial-delivery retry, recurrence after recovery, category filtering, ntfy authentication, rejected redirects and notification-identity reset. `tests/test_diagnostics_operations.py` distinguishes an offline printer from an unhealthy poller and checks the machine alert scope.

The following integration commands create their own disposable containers, volumes and internal test network. They never accept an existing installation's volume:

```bash
docker build --tag spoolmera:ci .
python scripts/container_restore_smoke.py --image spoolmera:ci
docker build --file Dockerfile.notifications --tag spoolmera:notifier-ci .
python scripts/notifier_container_smoke.py \
  --image spoolmera:notifier-ci --api-image spoolmera:ci
```

The recovery gate exercises a root-run offline restore onto a UID-10001 database, validates database and lock-file ownership, starts the normal non-root app, downloads another online backup and records new material movements. It also runs the packaged verifier with a writable workspace, verifies and restores a historical-schema backup, checks that incomplete current-schema candidates cannot replace the database, restores over corruption and a missing database, verifies the preserved prior bytes and rejects an unrelated SQLite file. Unit tests that require actual UID changes are skipped when the host does not map UID 10001; the Docker gate must still pass. The notifier gate resolves the actual Compose files against synthetic secret sentinels and sends one authenticated message to a disposable local HTTP stub across three separate container runs. A configured gate is not evidence that it passed; consult the CI run for the commit being installed.

For the isolated-slicer CI job, copy `tests/fixtures/slicer/ci.ini` into `slicer-profiles/ci.ini`, start the slicer Compose overlay with a fresh application database and export its generated `SPOOLMERA_BOOTSTRAP_TOKEN`. Then run `python scripts/slicer_smoke.py`. The test bootstraps only that fresh loopback instance and sends the closed 5 mm cube fixture through the authenticated API to the real PrusaSlicer executable. It checks the returned G-code without uploading it to any printer. The fixture profile is test data, not a physical-printer recommendation.
