# Testing Filament Manager

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

This instance uses the Compose project `filament-manager-test` and its own
`test_data` volume. Your normal instance's data is not used. Ports bind only to
loopback; printer connections are disabled by the empty IP allowlist.
Use `--port 8767` if 8766 is occupied. Avoid starting multiple test instances
against the same volume. Keep the selected port consistent for subsequent starts.

Stop while retaining test data:

```bash
docker compose -p filament-manager-test -f compose.test.yaml down
```

Only when you deliberately want to delete **all test inventory and accounts**:

```bash
docker compose -p filament-manager-test -f compose.test.yaml down -v
```

Existing `.env.test` is never overwritten. If it no longer contains the original
bootstrap token and setup is incomplete, repair that file before starting.

## Download a tested image from GitHub Actions

Open a successful CI run for the review pull request or `main`, then download
the artifact **filament-manager-test-linux-amd64** (available for seven days).
Extract it into a separate directory. It contains the same Docker image that
passed real HTTP checks and a restart/persistence check, plus a launcher.
The complete CI run must also have passed API/build and browser jobs.

```bash
docker load -i filament-manager-image.tar.gz
python scripts/start_test.py --prebuilt
```

Open **http://127.0.0.1:8766** and use the token in `.env.test` for first setup.
The artifact targets Linux amd64, including Docker Desktop with Linux containers
on x86-64 Windows. ARM hosts should build from source; no native ARM image was
validated by this workflow. SHA256SUMS contains the image archive checksum.
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
python -m pip install -r requirements-dev.txt
cd frontend
npm ci --no-audit --no-fund
npm run typecheck
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
