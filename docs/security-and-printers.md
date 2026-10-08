# Security, device integration and accounting

## Security controls

First-administrator setup requires `FILAMENT_BOOTSTRAP_TOKEN` (a unique, unpredictable string of at least 24 characters). Accounts use Argon2id (19 MiB memory, 2 iterations, parallelism 1) and a minimum of 14 characters. Previous development-only scrypt hashes can be verified and are upgraded on login. Random session credentials are stored only as SHA-256 hashes; browser cookies use HttpOnly, SameSite=Lax and Secure when configured. Session-bound CSRF headers protect state-changing operations.

Roles: **viewer** can inspect inventory, **editor** can change inventory and manage tracked jobs, and **admin** can additionally manage user accounts and printer configuration. Role changes revoke existing sessions. The last enabled administrator cannot be removed. Login attempts are throttled per client/user pair.

For WAN use keep network access restricted through a VPN or properly configured HTTPS reverse proxy, set `FILAMENT_PUBLIC_BASE_URL` to the actual origin and set `FILAMENT_COOKIE_SECURE=1`. Do not expose direct HTTP to the internet.

## Supported printer connections

This release has **read-only** adapters for Moonraker/Klipper and OctoPrint. No job submission, printer control or printer discovery is implemented. Printer endpoint hosts must be literal RFC1918 or ULA IPs and must be included exactly in `FILAMENT_PRINTER_ALLOWED_IPS`. The connector disables HTTP proxies and redirects, has a finite timeout and bounds the response length. Configure API keys using named `FILAMENT_PRINTER_TOKEN_*` environment variables; the database stores only the variable *name*, never the secret.

Use read-only or least-privilege keys at the printer controller when available. Printer firmware APIs might grant broader control than these HTTP requests use; inspect upstream permissions before pairing.

## G-code import

Importing a `.gcode`, `.gco` or `.gc` file (up to 16 MiB) reads slicer metadata for one estimated gram quantity. The bytes are not stored, executed or forwarded to the printer. You can alternatively enter a matching printer filename and estimated gram count manually. This is **print-job metadata import**, not automatic slicing.

One tracked job maps to one physical spool. Multi-material automatic mapping and waste/purge accounting are not supported.

## Completion and material deduction

The Moonraker adapter uses `GET /server/history/list` and the immutable job-history identifier. A local job is auto-debited **only if** the matched run was previously observed `in_progress` and later `completed` with the same unique identifier. The spool balance and a unique, job-linked movement are written together in one SQLite transaction.

Any missed observation (short job, restart), error, cancellation, insufficient stock or ambiguous result requires human review. OctoPrint's current-job status does not unambiguously prove successful completion, so it never automatically debits. Human confirmation debits the selected **estimate**, not sensor-measured grams; discard leaves inventory unchanged.

The poller runs in the single FastAPI runtime process. Do not run multiple Uvicorn workers without moving polling to a distributed scheduler and adding process-wide lease semantics.

## Versioned API

Existing `/api/integrations/v1/*` remains read-only; it now requires an authenticated browser session just like other API routes. The print-job mutation endpoints are separate, CSRF-protected role-gated routes.

## Known limitations

No OAuth/SSO, MFA, cloud-vendor printer integration, automated slicing, G-code uploading, isolation of separate tenants or physical filament weighing. SQLite backups must be consistent across WAL files. Upgrading to DB v3 is forward-only without restoring a backup.

Original device documentation:

- [Moonraker print history](https://moonraker.readthedocs.io/en/latest/external_api/history/)
- [Moonraker polling](https://moonraker.readthedocs.io/en/latest/external_api/introduction/)
- [OctoPrint current-job operations](https://docs.octoprint.org/en/main/api/job.html)
