# Security, device integration and accounting

## Security controls

First-administrator setup requires `SPOOLMERA_BOOTSTRAP_TOKEN` (a unique, unpredictable string of at least 24 characters). Accounts use Argon2id (19 MiB memory, 2 iterations, parallelism 1) and a minimum of 14 characters. Previous development-only scrypt hashes can be verified and are upgraded on login. Random session credentials are stored only as SHA-256 hashes; browser cookies use HttpOnly, SameSite=Lax and Secure when configured. Session-bound CSRF headers protect state-changing operations.

Roles: **viewer** can inspect inventory, **editor** can change inventory and manage tracked jobs, and **admin** can additionally manage user accounts and printer configuration. Role changes revoke existing sessions. The last enabled administrator cannot be removed. Login attempts are throttled per client/user pair.

For WAN use keep network access restricted through a VPN or properly configured HTTPS reverse proxy, set `SPOOLMERA_PUBLIC_BASE_URL` to the actual origin and set `SPOOLMERA_COOKIE_SECURE=1`. Do not expose direct HTTP to the internet.

## Supported printer connections

This release provides read-only adapters by default, with admin-only controller commands, file transfers, and print start when `SPOOLMERA_PRINTER_CONTROL_ENABLED=1` is set. No printer discovery is implemented. Printer endpoint hosts must be literal RFC1918 or ULA IPs and must be included exactly in `SPOOLMERA_PRINTER_ALLOWED_IPS`. The connector disables HTTP proxies and redirects, has a finite timeout and bounds the response length. Configure API keys using named `SPOOLMERA_PRINTER_TOKEN_*` environment variables; the database stores only the variable *name*, never the secret.

Use read-only or least-privilege keys for status-only connections, and narrowly scoped write permissions if available for opt-in physical actions. Printer firmware APIs may grant broader control than these HTTP requests use; inspect upstream permissions before pairing.

## Bambu Lab LAN adapter (community / non-official)

Bambu Lab X1, P1, A1 and A1 mini models may expose MQTT over TLS in **Developer Mode**, subject to firmware and device settings. This is **not a Bambu Lab officially supported integration**. Their [third-party integration announcement](https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/) explicitly warns that this mode is not covered by official support. Validate compatibility on your own device. This implementation never requires Bambu Cloud credentials.

**Configuration**

1. Ensure the printer and container are reachable on the same trusted LAN (or a deliberately secured local route), and enable Developer Mode on the printer if its firmware requires it. Never expose MQTT port 8883 to the internet.
2. Set `SPOOLMERA_PRINTER_ALLOWED_IPS=192.168.1.20` (use your actual **private** printer IP). Allowlist only exact addresses.
3. Set `SPOOLMERA_PRINTER_TOKEN_BAMBU1` to the printer's *LAN access code* (prefer Docker secrets via `SPOOLMERA_PRINTER_TOKEN_BAMBU1_FILE`), not your Bambu account password.
4. Obtain and verify the *printer's* TLS leaf certificate from a trusted local network, then pin its SHA-256 **DER** fingerprint: `openssl s_client -connect 192.168.1.20:8883 -showcerts </dev/null 2>/dev/null | openssl x509 -outform DER | openssl dgst -sha256`. Compare the certificate source with the printer you intend to connect to. Set `SPOOLMERA_BAMBU_CERT_SHA256_BAMBU1` to the 64 hexadecimal characters (without the `SHA2-256(stdin)=` prefix). Re-pin only after inspecting a legitimate certificate rotation; a mismatch disables the connection.
5. In **Printers → Add printer**, choose **Bambu Lab (LAN MQTT)**, use `mqtts://192.168.1.20:8883`, enter the physical device serial, and select `SPOOLMERA_PRINTER_TOKEN_BAMBU1` as the token-variable name.
6. Use **Test connection** to read current state, nozzle and bed temperatures, progress and AMS trays. Filament is never assigned by AMS telemetry. **Automatic estimated debit is off by default**, and only available as an explicit choice per registered Bambu print job.

The backend uses a short-lived MQTT connection, validates the exact pinned TLS certificate **before** sending credentials, subscribes to `device/<serial>/report` and requests a `pushall` snapshot. It neither discovers printers nor silently trusts self-signed certificates. If configured, printer commands pause, resume and stop use `device/<serial>/request`; they require admin authentication and the global opt-in `SPOOLMERA_PRINTER_CONTROL_ENABLED=1`. A broker PUBACK is **not confirmation of physical execution**; inspect the printer after each command. 

**Job filenames:** manually registered Bambu jobs can refer to an existing `.3mf` filename as reported by MQTT telemetry, in addition to G-code filenames. Archive uploads and slicing are not implied. Other controllers continue to accept G-code filenames only. Inspect a sliced 3MF (or G-code) for **per-tool material estimates** and explicitly assign each tool to its correct physical roll before registration. Each estimate uses **whole grams**, is advisory, and must account for purge/support waste where available.

**Limitations:** No Bambu FTP file upload, remote print start, camera streaming, Bambu cloud login, automatic AMS-to-spool mapping or guaranteed compatibility on newer firmware. Start and upload using Bambu Studio. MQTT task IDs and FINISH status are **community-observed telemetry, not vendor-certified, immutable print history or physical consumption measurements**. Auto-debit is optional per job; ambiguous print outcomes always need approval. AMS `remain` is a printer-reported percentage, not physical grams. All networking and protocol fields are bounded; credentials and certificate PINs are not persisted in SQLite.

## G-code import

Importing a `.gcode`, `.gco` or `.gc` file (up to 16 MiB) reads slicer metadata for one estimated gram quantity. **Metadata import** does not persist or upload the file. A separate privileged operation can upload a file to the printer. You can alternatively enter a matching printer filename and estimated gram count manually. This is **print-job metadata import**, not automatic slicing.

Tracked jobs can map multiple explicitly selected extruder tools to physical spools, with atomic multi-spool accounting. Automatic discovery of tool/material assignments, or automatic purge/waste estimates, is not supported. For Bambu, enabling **Auto-debit slicer estimates after a correlated Bambu print completes** stores an explicit per-job opt-in (existing jobs default off).

## Completion and material deduction

The Moonraker adapter uses `GET /server/history/list` and the immutable job-history identifier. A local job is auto-debited **only if** the matched run was previously observed `in_progress` and later `completed` with the same unique identifier. All linked spool balances and one unique movement per distinct physical spool and job are written together in one SQLite transaction.

For an opted-in Bambu job, the poller requires an exact filename match and valid nonzero `task_id` observed while `RUNNING`. It persists the run identity before processing a subsequent `FINISH` carrying the **same** ID and filename. A previously claimed task cannot be reused by a later job. Then it records the original per-tool slicer estimates in the existing atomic, idempotent stock journal, and releases any reservation. `SPOOLMERA_PRINTER_CONTROL_ENABLED` is **not** necessary for read-only MQTT polling or this bookkeeping; no physical print commands are sent.

If the printer omits an ID, changes the ID/filename, only reports `PAUSE`, ends with `FAILED`, loses necessary observations, has inadequate stock, or if automatic accounting was not explicitly enabled for that job, the job is left for **manual review**, not auto-debited. When a failed run includes observed layer counts, the review dialog can propose a **rough proportional starting value**, never an automatic partial debit: purge, supports, infill and filament use per layer vary. An operator must verify/edit the total for every physical roll, optionally using a scale.

Any missed observation (short job, restart), error, cancellation, insufficient stock or ambiguous result requires human review. OctoPrint's current-job status does not unambiguously prove successful completion, so it never automatically debits. Human confirmation debits the selected **estimate**, not sensor-measured grams; discard leaves inventory unchanged.

Polling still runs in the FastAPI runtime. A SQLite lease prevents overlapping scheduled pollers sharing one database, but a single Uvicorn worker is the supported default; lease expiry alone is not a substitute for a dedicated distributed worker at scale. Polling failures and timestamps are persisted for diagnostics. Moonraker history lookups use its unique run ID to recover entries outside the latest 25.

## Versioned API

Existing `/api/integrations/v1/*` remains read-only; it now requires an authenticated browser session just like other API routes. The print-job mutation endpoints are separate, CSRF-protected role-gated routes.

## Known limitations

No OAuth/SSO, MFA, native cloud-vendor API integration, automatic tool mapping, tenant isolation or physical filament weighing. The optional slicer now runs in a restricted, internal-only container; this reduces risk but is not a formal malware sandbox. Opt-in slicing, uploads, controls and signed vendor-neutral cloud bridge exist with explicit constraints in [Operations](operations.md). SQLite backups must be consistent across WAL files. Upgrading to DB v4 is forward-only without restoring a backup.

Original device documentation:

- [Moonraker print history](https://moonraker.readthedocs.io/en/latest/external_api/history/)
- [Moonraker polling](https://moonraker.readthedocs.io/en/latest/external_api/introduction/)
- [OctoPrint current-job operations](https://docs.octoprint.org/en/main/api/job.html)

## Durable physical command boundary

Printer commands are stored with a unique correlation ID and a lifecycle (`sending`, `acknowledged`, `unknown`, `confirmed`, `cleared`). A printer may act even when its HTTP response is lost: uncertain starts are never automatically resent. An administrator must verify the printer physically and record an explanation before clearing an unconfirmed command. Actual consumption is a separate transaction and requires a verified run identity or manual review.

Signed cloud relay aliases must be bound to one configured printer using `SPOOLMERA_CLOUD_PRINTER_<ALIAS>`. Signing authenticates the source but does not prove a successful print or physical material usage. Slicer workers receive only their own shared worker token, not the API bootstrap secret or controller credentials.

## v0.9 new trust boundaries

- Incoming scale events use opt-in, per-device HMAC-SHA256, timestamp limits, per-source durable replay detection and **mandatory human approval**. The relay does not implicitly weigh a physical spool or trust its claimed identity.
- Machine credentials are randomly generated, hashed at rest, scoped to read-only inventory or ledger events, shown only once and revocable. They never expose printer commands or bypass browser session authorization.
- External community catalog lookup is opt-in and restricted to one fixed HTTPS host with redirects disabled. All imported material properties remain subject to human confirmation.
- NFC and OpenPrintTag serial identifiers are references only, not authentication tokens. Web NFC is not supported by all browsers, nor is raw OpenPrintTag NDEF decoding provided.
- The optional local notification worker has no SQLite mount or printer credentials. Notifications can be duplicated after a failed cursor write and must never drive uncontrolled physical operations.
- Database backup download is administrator-only and contains user hashes and service data; protect it as a security-sensitive artifact.
