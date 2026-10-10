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

## Download a tested image from GitHub Actions

Open a successful CI run for the review pull request or `main`, then download
the versioned artifact **spoolmera-0.10.0-test-linux-amd64** (available for seven days).
Extract it into a separate directory. It contains the same Docker image that
passed real HTTP checks and a restart/persistence check, plus a launcher.
The complete CI run must also have passed API/build and browser jobs.

```bash
docker load -i spoolmera-image.tar.gz
python scripts/start_test.py --prebuilt
```

Open **http://127.0.0.1:8766** and use the token in `.env.test` for first setup.
The artifact targets Linux amd64, including Docker Desktop with Linux containers
on x86-64 Windows. ARM hosts should build from source; no native ARM image was
validated by this workflow. SHA256SUMS contains the image archive checksum.
`release.json` records the application/schema versions, source commit and Docker image ID.
SHA256SUMS covers the image archive, launcher, Compose file and accompanying metadata.
No secrets, database or pre-created accounts are shipped in the image.

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

The browser CI job creates **real Chromium screenshots from synthetic example data** after exercising the Angular UI in light, dark and mobile layouts. Successful runs publish the artifacts `ui-ux-previews` and `german-interface-previews`; failure evidence is kept separately. Five screenshots from the verified [2026-10-10 CI run](https://github.com/Cenn0/FilamentManager/actions/runs/38047886348) are committed under [`docs/screenshots/`](screenshots/README.md) and embedded in the project README, so images remain available after short-lived Actions artifacts expire. The [provenance guide](screenshots/README.md) maps the filenames and explains how to recapture them after frontend changes. They are visual regression evidence, **not** hardware compatibility results or a complete accessibility audit.

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

The test suite additionally checks legacy migrations through schema v10, online SQLite backups, durable printer command replay protection, worker token isolation, polling leases, role-restricted API routes, backend/Angular API contracts and stable cursor pagination. CI compiles Python, runs Angular unit tests, builds Angular, verifies generated API models and exercises browser and Docker persistence tests. The opt-in slicer image is built independently from the default runtime.

No automated tests certify a printer model, its firmware or safe physical G-code. Test a real machine while supervised before enabling write controls. The application is free/open source experimental software without a warranty.

The architecture suite also verifies that interrupted physical start commands change to an unknown, non-retryable state on restart and that repeated v5 initializations do not overwrite independent accounting decisions.

## v0.9 additional checks

New regressions cover schema upgrades, material properties, physical scale weighing, drying, spool reservations, per-tool G-code/3MF metadata, imported Spoolman snapshots, token scopes/revocation, tag uniqueness, signed scale receipts and review, cost estimates, label formats, verified online backup and offline restore, and durable notification cursors.

Device tests are mocked: they are **not** evidence of physical NFC/ESP32 compatibility, firmware version certification, native cloud-provider support or a penetration test. Test optional notification Compose with:

    docker compose -f compose.yaml -f compose.notifications.yaml config --quiet

## v0.10 recovery and worker gates

`tests/test_operations_recovery.py` exercises committed WAL growth, logical backup limits, growth while copying, deadline/storage bounds, exclusive backup slots, disconnect cleanup, invalid application backups, altered manifests, corrupt previous bytes, crash sidecars and restored credential/notification-identity reset. An API with a stopped poller must still block offline restore. `tests/test_polling_runtime.py` kills a disposable child process to verify prompt ownership recovery and checks that cancelling an asyncio task does not release a still-running thread's lock. A second application lifespan must fail before migrating an active database. Invalid operator settings must prevent startup.

`tests/test_notification_bridge.py` verifies quiet initialization, condition-based deduplication, partial-delivery retry, recurrence after recovery, category filtering, ntfy authentication, rejected redirects and notification-identity reset. `tests/test_diagnostics_operations.py` distinguishes an offline printer from an unhealthy poller and checks the machine alert scope.

The following integration commands create their own disposable containers, volumes and internal test network. They never accept an existing installation's volume:

```bash
docker build --tag spoolmera:ci .
python scripts/container_restore_smoke.py --image spoolmera:ci
docker build --file Dockerfile.notifications --tag spoolmera:notifier-ci .
python scripts/notifier_container_smoke.py \
  --image spoolmera:notifier-ci --api-image spoolmera:ci
```

The recovery gate exercises a root-run offline restore onto a UID-10001 database, validates database and lock-file ownership, starts the normal non-root app, downloads another online backup and records new material movements. It also restores over corruption and a missing database, verifies the preserved prior bytes and rejects an unrelated SQLite file. Unit tests that require actual UID changes are skipped when the host does not map UID 10001; the Docker gate must still pass. The notifier gate resolves the actual Compose files against synthetic secret sentinels and sends one authenticated message to a disposable local HTTP stub across three separate container runs. A configured gate is not evidence that it passed; consult the CI run for the commit being installed.

For the isolated-slicer CI job, copy `tests/fixtures/slicer/ci.ini` into `slicer-profiles/ci.ini`, start the slicer Compose overlay with a fresh application database and export its generated `SPOOLMERA_BOOTSTRAP_TOKEN`. Then run `python scripts/slicer_smoke.py`. The test bootstraps only that fresh loopback instance and sends the closed 5 mm cube fixture through the authenticated API to the real PrusaSlicer executable. It checks the returned G-code without uploading it to any printer. The fixture profile is test data, not a physical-printer recommendation.
