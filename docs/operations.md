# Print operations, slicing, cloud relays and multi-material jobs

> **Experimental opt-in functionality.** The APIs and unit tests do not certify
> hardware compatibility or make uploaded machine instructions safe. Run only
> behind HTTPS or VPN, restrict printer addresses, and physically supervise
> first tests. The Filament Manager application remains one Docker service.

## Printer control and file upload

Supported implemented API operations:

| Operation | Moonraker/Klipper | OctoPrint |
| --- | --- | --- |
| Status | `GET /printer/objects/query?print_stats` | `GET /api/job` |
| Transfer G-code | `POST /server/files/upload` | `POST /api/files/local` |
| Start tracked file | `POST /printer/print/start?filename=...` | `POST /api/files/local/{path}`, select+print |
| Pause / resume / cancel | `POST /printer/print/{action}` | `POST /api/job` with explicit command |

Vendor documentation: [Moonraker printer operations](https://moonraker.readthedocs.io/en/latest/external_api/printer/), [Moonraker file upload](https://moonraker.readthedocs.io/en/latest/external_api/file_manager/), [OctoPrint file APIs](https://docs.octoprint.org/en/main/api/files.html), [OctoPrint job commands](https://docs.octoprint.org/en/main/api/job.html).

1. Add **exact printer IP** to `FILAMENT_PRINTER_ALLOWED_IPS`. Only RFC1918/ULA addresses are accepted; DNS, redirects and proxy fallback are prohibited.
2. Configure optional `FILAMENT_PRINTER_TOKEN_<ALIAS>` in private `.env`, then add the printer as administrator. OctoPrint requires its token variable.
3. Set `FILAMENT_PRINTER_CONTROL_ENABLED=1` and restart the service to expose admin-only physical actions.
4. Register the job and filename under **Print jobs**. Use **Upload G-code** to send raw bytes (max 16 MiB, filename must match the job); upload never starts the printer automatically.
5. Review machine/material compatibility, tool mapping, temperatures and safety. Use **Start print** only while printer is idle. A physical start request does *not* establish a completed job or authorize inventory debit. Each start intent is persisted before contacting the controller. A timeout or lost acknowledgement is marked `unknown` and is **not retried automatically**. The administrator can inspect the command on **Print jobs** and clear it only after physically confirming the printer did not start, recording the reason. Moonraker's independent history poller retains its previous exact-run completion rules; OctoPrint completions still require manual review.

Cancellation of physical printing flags currently observed active jobs for manual material review. A request to stop tracking **does not** stop the physical printer. APIs intentionally expose no arbitrary G-code command execution, no firmware update, no print-temperature override, and no arbitrary controller URLs.

**Controller credentials:** stored in environment only; actual controller roles must allow the needed action. `FILAMENT_PRINTER_CONTROL_ENABLED=1` increases physical risk. Enabling write methods is not equivalent to vendor certification.

## Automatic STL slicing (optional isolated worker)

Slicing is **not installed in the default API image**. The opt-in Compose overlay starts a separate `slicer-worker` container and connects it to the API via an internal-only Docker network. The worker has no printer credentials, no database volume, no public port and no access to the default Docker network. It runs as non-root with a read-only filesystem, limited CPU/RAM/PIDs and bounded temporary storage.

1. Create `slicer-profiles/` next to `compose.yaml`. Put only operator-reviewed PrusaSlicer `.ini` profiles in it, exported for the packaged PrusaSlicer version. They are mounted read-only to the worker.
2. Generate a random 32+ character `FILAMENT_SLICER_WORKER_TOKEN` and place it in the private `.env` file. It must match on the API and worker; Compose sets it for the worker.
3. Start with:

   ```bash
   docker compose -f compose.yaml -f compose.slicer.yaml up -d --build
   ```

4. As administrator, upload one STL (8 MiB maximum), select an approved profile and click **Slice and download G-code**. Output is limited to 16 MiB. The G-code is **not** transferred or started automatically.

The worker uses a fixed executable path, no shell, an isolated temporary directory, a 60-second slicing timeout and a single-process semaphore. Profile post-processing commands are rejected. Slicing malicious geometry is not proven safe simply because the process is isolated; supervise first prints and review G-code. API requests fail closed when the worker token/network is not configured.

## Multi-material job mapping

In **Print jobs**, register the first tool (T0) with its physical spool ID and estimate in grams. Use **Add another material/tool** for each additional tool up to eight total tool mappings (valid tool indices 0–15, unique per job). The backend rejects repeated tool IDs and insufficient aggregate stock on the same spool.

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

Set `FILAMENT_CLOUD_HMAC_FARM=<32+ character random secret>` and `FILAMENT_CLOUD_PRINTER_FARM=<printer ID>` privately, then restart. Relays cannot mark jobs of other printers; a missing binding is rejected. External bridge example:

```http
POST /api/cloud/hooks/FARM
X-Filament-Timestamp: 1791470000
X-Filament-Signature: sha256=<64 lowercase hexadecimal characters>
Content-Type: application/json

{"event_id":"remote-job-000001","job_id":42,"status":"completed"}
```

The timestamp must be the current Unix epoch seconds (the example is illustrative). Compute:

```python
import hashlib, hmac, json, os, time
body = json.dumps({"event_id":"remote-job-000001","job_id":42,"status":"completed"}).encode()
stamp = str(int(time.time()))
key = os.environ["FILAMENT_CLOUD_HMAC_FARM"]
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

- The admin-only `GET /api/diagnostics` shows job totals, pending/uncertain controller commands and last printer polling outcomes, without secrets.
- `GET /api/audit` gives an admin-only chronological record of user and automation actions. Existing records from older versions cannot be retrospectively attributed to a person.
- Use `python scripts/backup.py backup.sqlite3 --database /data/filaments.sqlite3` where the data volume is mounted. It performs a consistent online SQLite backup and integrity check; do not overwrite existing backups or copy only the live database file.
- REST `GET /api/inventory/v2/spools?limit=50&cursor=<id>` supports filtered cursor pagination while the original `/api/spools` array remains backwards-compatible.
- Keep only one effective polling lease owner per database. A bounded SQLite lease prevents duplicate scheduled scans after accidental multiple worker startup, but a single application worker remains the supported deployment.
