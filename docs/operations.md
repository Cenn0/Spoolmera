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
5. Review machine/material compatibility, tool mapping, temperatures and safety. Use **Start print** only while printer is idle. A physical start request does *not* establish a completed job or authorize inventory debit. Moonraker's independent history poller retains its previous exact-run completion rules; OctoPrint completions still require manual review.

Cancellation of physical printing flags currently observed active jobs for manual material review. A request to stop tracking **does not** stop the physical printer. APIs intentionally expose no arbitrary G-code command execution, no firmware update, no print-temperature override, and no arbitrary controller URLs.

**Controller credentials:** stored in environment only; actual controller roles must allow the needed action. `FILAMENT_PRINTER_CONTROL_ENABLED=1` increases physical risk. Enabling write methods is not equivalent to vendor certification.

## Automatic STL slicing (administrator only)

Optional Docker installation on Debian trixie includes the distro's packaged PrusaSlicer CLI (trixie package 2.9.2). **It is not part of the default image**, and its INI profile compatibility depends on that packaged version.

1. Create the operator-owned `slicer-profiles/` directory adjacent to Compose files. Add `<profile>.ini` files exported for the installed PrusaSlicer version. These are not web-uploadable, and must be reviewed for printer geometry, nozzle, temperature and material parameters.
2. Set `FILAMENT_SLICER_ENABLED=1` in the `.env` file.
3. Start with:
   ```bash
   docker compose -f compose.yaml -f compose.slicer.yaml up -d --build
   ```
4. As administrator in **Print jobs**, upload one STL (8 MiB maximum), select an allowlisted profile and choose **Slice and download G-code**. The generated G-code is downloaded, **not sent to the printer**. Manually inspect it, then use the separate registered-job and upload workflow if desired.

The server invokes a fixed, absolute PrusaSlicer executable and approved INI profile path without a shell, strips credentials from its environment, uses an isolated temporary directory, has a 60-second timeout and limits G-code output to 16 MiB. The process has no dedicated security sandbox beyond the existing non-root, read-only Docker runtime; even with resource limits, malformed untrusted models can exploit slicer bugs. **Best practice for publicly shared or adversarial model files is a separate sandboxed slicer worker**, rather than enabling this in the main container. No asynchronous queue or multi-model batch slicing is provided.

INI post-processing scripts are blocked for approved profiles. This is defense-in-depth only, not a formal proof that arbitrary third-party profiles are safe. The operator remains responsible for selecting and checking profiles.

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

Set `FILAMENT_CLOUD_HMAC_FARM=<32+ character random secret>` privately and restart. External bridge example:

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
