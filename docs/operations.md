# Print operations, slicing, cloud relays and multi-material jobs

> **Experimental opt-in functionality.** The APIs and unit tests do not certify
> hardware compatibility or make uploaded machine instructions safe. Run only
> behind HTTPS or VPN, restrict printer addresses, and physically supervise
> first tests. The default installation remains one Docker service; optional slicing uses a separate internal-only worker.

## Printer control and file upload

Supported implemented API operations:

| Operation | Moonraker/Klipper | OctoPrint |
| --- | --- | --- |
| Status | `GET /printer/objects/query?print_stats` | `GET /api/job` |
| Transfer G-code | `POST /server/files/upload` | `POST /api/files/local` |
| Start tracked file | `POST /printer/print/start?filename=...` | `POST /api/files/local/{path}`, select+print |
| Pause / resume / cancel | `POST /printer/print/{action}` | `POST /api/job` with explicit command |

**Bambu Lab LAN MQTT is not included in the HTTP-controller table:** its community/non-official integration reads selected status/AMS telemetry and can optionally pause, resume or stop a job. It also supports **per-job, explicitly enabled** consumption of the original slicer-estimated whole grams when MQTT reports the same nonzero task ID and filename from a previously observed running print through FINISH. Ambiguous/failed prints require review, and the printer does not physically weigh filament. No automatic AMS-to-spool mapping is performed. It does not upload or remotely start a file, and requires Developer Mode compatibility plus a verified, pinned TLS leaf certificate. See [Bambu LAN configuration and limitations](security-and-printers.md#bambu-lab-lan-adapter-community--non-official). No real Bambu hardware is certified.

Vendor documentation: [Moonraker printer operations](https://moonraker.readthedocs.io/en/latest/external_api/printer/), [Moonraker file upload](https://moonraker.readthedocs.io/en/latest/external_api/file_manager/), [OctoPrint file APIs](https://docs.octoprint.org/en/main/api/files.html), [OctoPrint job commands](https://docs.octoprint.org/en/main/api/job.html).

1. Add **exact printer IP** to `SPOOLMERA_PRINTER_ALLOWED_IPS`. Only RFC1918/ULA addresses are accepted; DNS, redirects and proxy fallback are prohibited.
2. Configure optional `SPOOLMERA_PRINTER_TOKEN_<ALIAS>` in private `.env`, then add the printer as administrator. OctoPrint requires its token variable.
3. Set `SPOOLMERA_PRINTER_CONTROL_ENABLED=1` and restart the service to expose admin-only physical actions.
4. Register the job and filename under **Print jobs**. Use **Upload G-code** to send raw bytes (max 16 MiB, filename must match the job); upload never starts the printer automatically.
5. Review machine/material compatibility, tool mapping, temperatures and safety. Use **Start print** only while printer is idle. A physical start request does *not* establish a completed job or authorize inventory debit. Each start intent is persisted before contacting the controller. A timeout or lost acknowledgement is marked `unknown` and is **not retried automatically**. The administrator can inspect the command on **Print jobs** and clear it only after physically confirming the printer did not start, recording the reason. Moonraker's independent history poller retains its previous exact-run completion rules; OctoPrint completions still require manual review.

Cancellation of physical printing flags currently observed active jobs for manual material review. A request to stop tracking **does not** stop the physical printer. APIs intentionally expose no arbitrary G-code command execution, no firmware update, no print-temperature override, and no arbitrary controller URLs.

**Controller credentials:** stored in environment only; actual controller roles must allow the needed action. `SPOOLMERA_PRINTER_CONTROL_ENABLED=1` increases physical risk. Enabling write methods is not equivalent to vendor certification.

## Automatic STL slicing (optional isolated worker)

Slicing is **not installed in the default API image**. The opt-in Compose overlay starts a separate `slicer-worker` container and connects it to the API via an internal-only Docker network. The worker has no printer credentials, no database volume, no public port and no access to the default Docker network. It runs as non-root with a read-only filesystem, limited CPU/RAM/PIDs and bounded temporary storage.

1. Create `slicer-profiles/` next to `compose.yaml`. Put only operator-reviewed PrusaSlicer `.ini` profiles in it, exported for the packaged PrusaSlicer version. They are mounted read-only to the worker.
2. Generate a random 32+ character `SPOOLMERA_SLICER_WORKER_TOKEN` and place it in the private `.env` file. It must match on the API and worker; Compose sets it for the worker.
3. Start with:

   ```bash
   docker compose -f compose.yaml -f compose.slicer.yaml up -d --build
   ```

4. As administrator, upload one STL (8 MiB maximum), select an approved profile and click **Slice and download G-code**. Output is limited to 16 MiB. The G-code is **not** transferred or started automatically.

The worker uses a fixed executable path, no shell, an isolated temporary directory, a 60-second slicing timeout and a single-process semaphore. PrusaSlicer is explicitly capped at two threads after loading the approved profile, matching the default Compose worker CPU allocation even when its host exposes more CPUs; the profile cannot raise that subprocess budget. The shipped CLI documents [the threads option](https://manpages.debian.org/trixie/prusa-slicer/prusa-slicer.1.en.html). Profile post-processing commands are rejected. Slicing malicious geometry is not proven safe simply because the process is isolated; supervise first prints and review G-code. API requests fail closed when the worker token/network is not configured.

## Multi-material job mapping

In **Print jobs**, register each tool with its physical spool ID and estimate in grams. A job may use only a nonzero tool such as T3; the application does not invent a T0 mapping. Use **Add another material/tool** for each additional tool up to eight total tool mappings (valid tool indices 0–15, unique per job). The backend rejects repeated tool IDs and insufficient aggregate stock on the same spool.

`POST /api/jobs/multi` example:

```json
{
  "printer_id": 1,
  "file_name": "multicolor.gcode",
  "note": "Two-material bracket",
  "materials": [
    {"tool": 0, "spool_id": 12, "estimated_g": 45},
    {"tool": 1, "spool_id": 15, "estimated_g": 8}
  ]
}
```

Completion debits all assigned *physical spools in one SQLite transaction*. Each distinct consumed spool receives one immutable movement record per job. If any spool is missing, archived or understocked, none is debited; the job goes to manual review. Legacy single-material jobs remain supported after the v4 migration. Material amount estimates should include any purge, prime tower, skirt and waste, if produced by the slicer; no automatic slicer tool-weight parsing or hardware slot detection is implemented.

## Cloud event bridge (vendor neutral)

This is an inbound **signed adapter contract**, not native vendor-cloud authentication or printer control. An independently deployed bridge can translate Bambu/Prusa/other cloud events into this schema after the operator verifies that provider's supported API and permissions. Vendor compatibility is **not** claimed.

Set `SPOOLMERA_CLOUD_HMAC_FARM=<32+ character random secret>` and `SPOOLMERA_CLOUD_PRINTER_FARM=<printer ID>` privately, then restart. Relays cannot mark jobs of other printers; a missing binding is rejected. External bridge example:

```http
POST /api/cloud/hooks/FARM
X-Spoolmera-Timestamp: 1791470000
X-Spoolmera-Signature: sha256=<64 lowercase hexadecimal characters>
Content-Type: application/json

{"event_id":"remote-job-000001","job_id":42,"status":"completed"}
```

The timestamp must be the current Unix epoch seconds (the example is illustrative). Compute:

```python
import hashlib, hmac, json, os, time
body = json.dumps({"event_id":"remote-job-000001","job_id":42,"status":"completed"}).encode()
stamp = str(int(time.time()))
key = os.environ["SPOOLMERA_CLOUD_HMAC_FARM"]
signature = hmac.new(key.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
print(stamp, signature)
```

Events require HMAC-SHA256, timestamp within 5 minutes, 8 KiB body limit, and globally unique `(source,event_id)`. Reusing the same event ID and body is acknowledged without reprocessing; differing contents are rejected. The source may contain only uppercase letters, digits and underscores.

A reported completion/failure/cancellation only moves active tracking to **needs_review**. It does *not* debit inventory: a signed report is not evidence that the actual print finished or that the printed material matched the mapping. This bridge is available without browser cookies specifically for HMAC-authenticated machines. The operator should restrict its route at the reverse proxy and never log HMAC secrets. Admins can inspect the last 100 event receipts under **Integrations**.

## Auth and support classification

- **Works at application/API level:** mock-tested Python routes, Angular UI and the existing Docker instance.
- **Officially documented upstream APIs:** Moonraker and OctoPrint requests linked above; actual controller version, firmware configuration, plugin compatibility and token permission must be checked with the device.
- **Best practice:** least-privilege printer credentials, VPN/HTTPS, private controller VLAN, read-only or sandboxed slicer processes, reviewed printer profiles, explicit file/physical command confirmation, database snapshots.
- **Security:** controller write support and slicing are disabled by default. No native cloud auth/SSO. No safety certification for physical printing, machine G-code or untrusted STL.

## Operations, backups and diagnostics

- The editor/admin **Operations** page and `GET /api/diagnostics` show application/schema versions, supervised poller state, lease owner/expiry, heartbeat, printer observation freshness, pending/uncertain commands and uploads, storage reserve and backup/restore metadata. Historical material-mapping mismatches are read-only warnings; the application never guesses how to rewrite a past ledger.
- `GET /api/audit` gives an admin-only chronological record of user and automation actions. Existing records from older versions cannot be retrospectively attributed to a person.
- Use `python scripts/backup.py backup.sqlite3 --database /data/spoolmera.sqlite3` where the data volume is mounted. The CLI creates a consistent single-file SQLite snapshot plus a SHA-256 manifest and refuses to overwrite either file. Keep both files together. Never copy just the live SQLite main file while writes may remain in its WAL.
- REST `GET /api/inventory/v2/spools?limit=50&cursor=<id>` supports filtered cursor pagination while the original `/api/spools` array remains backwards-compatible.
- One API process and a local SQLite volume are the supported deployment. An application lock is held from before migration until the poller has fully stopped; a second process cannot initialize the same database. A separate kernel file lock covers the whole poller lifetime; the operating system releases it after a hard process exit. Only the process holding that lock may replace an orphaned SQLite polling lease. The short lease is renewed while polling runs. Cancellation retains ownership until any running controller-request thread exits. Physical printer operation locks remain independent and are never cleared merely to restart polling.

`/api/health` is a liveness probe. `/api/ready` additionally requires the poller task and its ownership to be healthy. An offline printer is a separate diagnostic condition; it does not itself make the application unready. The poller samples all enabled printers and keeps per-printer attempts, successes and failure counts. If a configured controller is deliberately unavailable, disable that printer to stop its polling and alerts.

Startup rejects invalid polling intervals, backup timeouts, boolean feature flags and public origins. The polling interval accepts 10–300 seconds. `SPOOLMERA_BACKUP_TIMEOUT_SECONDS` defaults to 30 seconds (1–300); `SPOOLMERA_STORAGE_RESERVE_MIB` defaults to 64 MiB (1–4096). Enabled slicing requires the matching internal-worker configuration.

## Material care and imports (v0.9)

Use the Weigh spool action to enter gross mass and physical empty-spool tare; the balance delta is recorded with its explanation. It refuses impossible measurements or measurements that would violate active reservations. Drying records capture completed temperature, duration, timestamp and a note. **No general-purpose material-drying schedule is inferred.**

Set SPOOLMERA_CATALOG_ENABLED=1 to browse optional Open Filament Database records. The API uses only a fixed HTTPS origin and stores read-only previews in the application data volume. Review imported values before saving as a product.

Under Integrations, choose Import from Spoolman. Supply a JSON array from a Spoolman list-spools API response (or an object containing a spools array); select a unique source ID for that original Spoolman installation. Preview, then confirm. Imports are create-only, transactional and idempotent. No historical movements or user accounts are migrated.

## Print readiness, feeder slots and per-tool G-code/3MF

In Printers, manually assign each tool/slot to the loaded physical spool. In Print jobs, inspect optional G-code/3MF metadata to extract supported per-tool gram estimates. Proposals from recorded printer slots require explicit confirmation. Verify the file, profile and actual loaded spool independently. Reserve material to prevent other pending job reservations from oversubscribing the same stock; reservations never subtract physical inventory.

## NFC and tag association

Register a physical tag serial ID in spool details (nfc, openprinttag or custom). The Spools page resolves an ID received from a keyboard-style NFC reader or an optional Web NFC reader where supported. Web NFC needs a compatible mobile browser, hardware and HTTPS. This is not full OpenPrintTag payload decoding and the tag ID is not a login credential.

## Signed physical scale events

Set a random 32+ character environment secret, for example SPOOLMERA_SCALE_HMAC_WORKSHOP, and enable an external device to send JSON to POST /api/scales/hooks/WORKSHOP. Example exact JSON bytes:

    {"event_id":"scale-00000001","spool_uid":"930ff9ed-0d12-4124-8e28-39d21cdd47b2","gross_g":850,"tare_g":230}

The request requires X-Spoolmera-Timestamp with current Unix seconds and X-Spoolmera-Signature containing sha256= followed by the HMAC-SHA256 hex digest of: the ASCII timestamp, a single dot byte and the exact raw JSON body, keyed with the device secret.

A signed report is only queued for authenticated review. In Integrations an editor can approve or discard a measurement; approval rechecks net mass and reservations and atomically records the inventory movement. Event IDs cannot be replayed with a different payload. This is a vendor-neutral adapter contract, not guaranteed compatibility with ESP32/ESPHome firmware.

## Automation tokens and notifications

An administrator creates and revokes narrowly scoped machine tokens under Integrations. `GET /api/automation/v1/spools` requires `inventory_read`. The movement feed and `GET /api/automation/v1/alerts` require `events_read`. Every machine endpoint requires `Authorization: Bearer <issued token>`; a browser session is not a substitute. The existing ordered movement feed remains available for other local integrations.

The optional notifier reads a snapshot of active alerts with an `events_read` token. Configure `SPOOLMERA_AUTOMATION_TOKEN` and `SPOOLMERA_NTFY_URL` privately; set a separate `SPOOLMERA_NTFY_TOKEN` when the receiving ntfy server requires Bearer authentication. Use HTTPS when the endpoint leaves a protected local network. Then run:

    docker compose -f compose.yaml -f compose.notifications.yaml up -d --build

`SPOOLMERA_NOTIFICATION_CATEGORIES` is a comma-separated subset of `low_stock`, `job_review` and `printer_offline`; all three are selected by default. Printer connection alerts begin after three consecutive failed attempts. The first snapshot forms a quiet baseline. Later new conditions are delivered once per active condition, with a durable state update after each acknowledgement. A condition can notify again after it resolves and recurs. Changes to a still-active alert's description do not generate repeated messages. At most 25 new messages are sent in one cycle; further pending alerts remain for the next cycle.

Delivery remains at least once: a crash between an acknowledgement and durable state can duplicate one message. Failed deliveries are retried on the next polling cycle. Incomplete server snapshots are rejected rather than incorrectly treating omitted conditions as resolved. The old numeric movement cursor is upgraded to the new baseline automatically. Home Assistant may keep using the versioned read-only machine endpoints independently.

The notifier receives only its explicit configuration variables. The shared `.env` file is not passed wholesale into this container. It has no application database mount, bootstrap secret, printer credentials, slicer token, cloud-HMAC key or scale-HMAC key. Its image has no application code or third-party Python packages.

## Backups, restoration and label formats

Administrators can download a verified online SQLite snapshot. The download includes committed WAL pages and is limited to 256 MiB of logical database/snapshot size, one simultaneous creation/download, a configured time limit and a free-space reserve. The response exposes its SHA-256 in `X-Backup-SHA256`. Disconnects clean up the temporary file; the next backup also cleans orphaned snapshots from a crashed process. Backups contain password hashes, session records, token hashes and inventory; protect them as sensitive data.

For scheduled or larger backups, run the CLI inside the normal container so it uses the same UID and mounted volume:

```bash
docker compose exec -T spoolmera python scripts/backup.py \
  /data/backups/before-upgrade.sqlite3 --database /data/spoolmera.sqlite3
```

Choose a new filename for each backup, then copy the `.sqlite3` and `.manifest.json` files to independent storage. Files in the same Docker volume do not protect against losing that volume. The CLI defaults to a 300-second time limit and supports `--timeout-seconds` up to 3600.

### Verify a backup and rehearse its upgrade

Use the application version you intend to restore into to check a completed,
standalone backup before changing your installation:

```bash
docker compose run --rm --no-deps --entrypoint python spoolmera \
  scripts/verify_backup.py /data/backups/before-upgrade.sqlite3 \
  --work-dir /data --json
```

The host equivalent is `python scripts/verify_backup.py BACKUP --json`.
Verification does not take an active database as its input, start the API or
poller, contact a printer, or replace an installation. A separate, completed
backup can be checked while the application continues to use its live database.
Do not point the verifier at that live database, even if it currently has no
visible WAL file.

The verifier checks any adjacent checksum manifest, application identity,
supported schema, SQLite integrity and foreign keys. It runs the real database
initializer and forward migrations on a private temporary copy, then checks all
required current tables and columns. A backup already claiming the current
schema is checked before initialization as well, so missing tables cannot be
silently recreated as empty data. The candidate is checkpointed into a complete
single SQLite file before it is accepted. This validates database initialization
and structure, not every possible SQL constraint, hardware state or host setup.

The original backup and manifest stay unchanged. Legacy backups and UI downloads
without a manifest remain accepted if their database checks pass; the report
explicitly says `manifest_status: "absent"`. A matching checksum proves consistency
with that manifest, not who created the backup. Keep backups in trusted storage.

Each check uses a temporary directory with mode 0700 and removes its candidate
on success or failure. `--work-dir` must name an existing writable directory
with enough space for the candidate, migration work and a 64 MiB reserve. Use
`--work-dir /data` in the standard container: its 64 MiB `/tmp` cannot also hold
the reserve and a database. `--snapshot-timeout-seconds` accepts 1–3600 seconds
(default 300) and limits the SQLite snapshot operation; it is **not a total time
limit** for source hashing or the subsequent migration.

`--json` writes one report suitable for backup automation:

| Field | Meaning |
| --- | --- |
| `report_version`, `status` | Report contract version `1`; `ok` or `error` |
| `application`, `application_version` | Application used to perform the check |
| `source_schema`, `target_schema`, `migration_required` | Original schema and tested upgrade destination |
| `manifest_status` | `verified` or `absent` |
| `source_size_bytes`, `source_sha256` | Size and SHA-256 of the unchanged original file |
| `error.code`, `error.message` | Failure classification and sanitized explanation on error |

Exit status is `0` for success, `1` for a failed check or unavailable workspace,
and `2` for invalid command arguments. Error reports omit the success-only fields.
Neither report form includes inventory records, account data, credentials or
file paths. Verify the copied backup on its independent storage as well as the
local snapshot, and keep a full restore rehearsal in your upgrade procedure.

### Restore a verified backup

To restore, fully stop the application and optional notifier. Use the same Compose overlays that started your installation when stopping those services. For the default installation and a backup already present in its data volume:

```bash
docker compose stop
docker compose run --rm --no-deps --entrypoint python spoolmera \
  scripts/restore.py /data/backups/before-upgrade.sqlite3 \
  /data/spoolmera.sqlite3 --confirm
docker compose up -d
```

The equivalent host command is `python scripts/restore.py BACKUP DATABASE --confirm`; the user must be able to preserve the existing database's UID/GID and permissions. The container command avoids the usual mismatch between a host administrator and runtime UID 10001. An administrator's root-run restore also preserves the operation-lock owners; recovery of a missing database inherits the data directory's UID/GID. The utility repeats the same verification and real migration rehearsal as the backup verifier on its staging copy. The source must be a standalone snapshot without WAL/SHM/journal files. A healthy unrelated SQLite file is rejected. Only after the candidate reaches the current schema and required structure does restore revoke its recovered credentials and preserve the previous target as raw bytes, even if it is corrupt, along with a quarantine manifest. It then replaces the completed single-file candidate atomically. A rejected candidate leaves the target database and its sidecars unchanged.

A clean shutdown should leave no WAL/SHM sidecars. If a stopped crashed instance still has sidecars, `--quarantine-sidecars` explicitly preserves their raw bytes before replacement. Never remove a live WAL file or use this option while the application is running. The kernel operation locks reject an active application or another recovery operation. Prior-state quarantine files make no claim of database integrity.

Restore revokes all browser sessions and machine tokens contained in the old snapshot, clears only polling leases, and generates a new notification stream identity. Sign in with the account credentials from the restored backup, issue new automation tokens, update the notifier configuration and restart it. The notifier reports the changed identity and establishes a new baseline instead of silently skipping reused row IDs. Independently inspect unresolved printer commands, current physical material and any historical mapping warnings before resuming normal work. No restore command starts a printer or automatically clears an uncertain physical operation.

Exercise the full recovery procedure on a separate test installation before relying on it for your own backups. Only restore to the same or a newer supported application schema; a downgrade requires the earlier application version and its matching pre-upgrade backup.

Label pages support `size=60x40` or `size=50x30` query parameters in millimeters. Always select the matching stock and 100% print scaling.

The web interface and printed labels support English and German. Labels use an explicit `lang=en` or `lang=de` query parameter first, then the interface language stored in the `spoolmera_language` browser cookie, then supported browser `Accept-Language` preferences; otherwise they use English. Size-switch links retain the selected language. Language selection changes display text and number formatting only; product names, spool identities, QR targets and access requirements remain unchanged.


### Host recovery privileges

The **recommended** restore is the non-root Compose command above, with the
application and all optional services stopped. Running the host script as root
is not needed for ordinary installations and increases the impact of mistakes.
For exceptional host recovery, inspect database-directory ownership and all
existing operation-lock entries before privileged execution; symbolic links and
non-regular/multiply-linked lock files are rejected. Do not operate on an
untrusted, writable data directory while granting privileges to recovery tools.
