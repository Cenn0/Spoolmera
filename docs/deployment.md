# Deployment, configuration and upgrades

[← Documentation index](README.md) · [← Project README](../README.md)

These instructions apply to the experimental **Spoolmera v0.10.0** single-container default. Optional printer control, slicing workers and notification bridges are documented separately in [Operations](operations.md).

## Requirements and first installation

Docker with Compose, a host with sufficient storage, and Git access to the public repository at `https://github.com/Cenn0/Spoolmera`. No GitHub account is needed to clone public source code.

```bash
git clone https://github.com/Cenn0/Spoolmera.git
cd Spoolmera
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Paste the resulting random value into `SPOOLMERA_BOOTSTRAP_TOKEN=` in your untracked `.env`. An empty token deliberately blocks initial setup. The token must be at least 24 characters; use the generated 32+ character secret. Then:

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Open **http://127.0.0.1:8765** on the Docker host and create the first administrator using that token and a **14+ character password**. No default admin account exists. Inspect startup failures using `docker compose logs --tail=100 spoolmera`.

The Docker service serves compiled Angular through FastAPI; the runtime does **not** need Node.js. Persistent SQLite data lives in the named volume `spoolmera_data`, at `/data/spoolmera.sqlite3` inside the container. Exactly **one API process per SQLite database** is the supported operating model. Do not share one SQLite volume across several application workers.

## Remote access, HTTPS and QR links

The default Compose port binding is `127.0.0.1:8765:8765`. This deliberately restricts access to the Docker host. For LAN/mobile access, use an HTTPS reverse proxy **on that host** or a protected VPN. Route the public hostname to the loopback-bound service and configure the real client-visible origin in `.env`:

```dotenv
SPOOLMERA_PUBLIC_BASE_URL=https://spoolmera.example.com
SPOOLMERA_COOKIE_SECURE=1
```

Restart with `docker compose up -d`. The public base URL is also embedded in newly generated QR labels and checked against browser Origin. It must be an HTTP(S) origin, with no credentials, path, query or fragment. Test authentication, edits and label scans from the actual phone/browser. A QR code pointing to `127.0.0.1` cannot work on another device.

**Security recommendation:** Never expose cleartext login or printer-controller endpoints on the public internet. Keep printer IPs restricted, do not bypass CSRF/Origin checks to resolve proxy errors, and read the [security instructions](security-and-printers.md) before using hardware.

## Configuration essentials

The complete operator template is [`.env.example`](../.env.example).

| Setting | Meaning |
| --- | --- |
| `SPOOLMERA_BOOTSTRAP_TOKEN` | Initial admin setup secret; protect it and do not commit `.env` |
| `SPOOLMERA_DB_PATH` | Compose sets `/data/spoolmera.sqlite3`; changing it can create an empty instance |
| `SPOOLMERA_PUBLIC_BASE_URL` | External browser Origin and QR destination |
| `SPOOLMERA_COOKIE_SECURE` | Set `1` behind HTTPS |
| `SPOOLMERA_PRINTER_ALLOWED_IPS` | Comma-separated exact private printer IP allowlist, empty by default |
| `SPOOLMERA_PRINTER_CONTROL_ENABLED` | `0` by default; opt-in admin-only physical printer actions |
| `SPOOLMERA_PRINTER_POLL_SECONDS` | `30` by default; valid 10–300 |
| `SPOOLMERA_SLICER_ENABLED` | `0` by default; requires separate isolated worker overlay |
| `SPOOLMERA_CATALOG_ENABLED` | `0` by default; optional external catalog access |
| `SPOOLMERA_BACKUP_TIMEOUT_SECONDS` / `SPOOLMERA_STORAGE_RESERVE_MIB` | Default 30 s / 64 MiB for online backup bounds |

Printer credentials, Bambu certificate pins, signed event relay keys and worker tokens are documented in [Operations](operations.md) and [Security](security-and-printers.md). Keep secrets in private environment files or mounted secret files, **never** in versioned documentation.

## Data, backups and upgrades

Stop the application **without removing its volume**:

```bash
docker compose down
```

**Never run `docker compose down -v` unless you intend to delete the inventory and user database.**

The administrator UI can download an online SQLite snapshot. Backups contain sensitive account hashes and inventory. For a consistent CLI backup inside the container, use a new filename:

```bash
docker compose exec -T spoolmera python scripts/backup.py \
  /data/backups/before-upgrade.sqlite3 \
  --database /data/spoolmera.sqlite3
```

Copy **both** the `.sqlite3` and `.manifest.json` to a different storage device/host; a copy left inside the same Docker volume is not a disaster-recovery backup. Backups and UI downloads have time, size and available-space limits described in [Operations](operations.md).

Before upgrading: take a backup and verify it using the intended target application version:

```bash
docker compose run --rm --no-deps --entrypoint python spoolmera \
  scripts/verify_backup.py /data/backups/before-upgrade.sqlite3 \
  --work-dir /data --json
```

This command tests actual database initialization and migration on a temporary
copy without replacing the running installation. It reports the source/target
schema, original checksum and whether a manifest was verified. Use the image
built from the reviewed target revision for an upgrade rehearsal; the installed
old image only verifies against its own schema. The host command is
`python scripts/verify_backup.py BACKUP --json`. See the [verification contract
and resource limits](operations.md#verify-a-backup-and-rehearse-its-upgrade).

Test full restoration in the isolated stack, review changes and migration prerequisites, update to the chosen reviewed commit, then run `docker compose up -d --build`. Recheck users, recorded balances, movement history, pending job reviews and container health. Version-gated migrations support documented upgrades; **database downgrades are not guaranteed**.

### Offline restore

Read the **complete** [restore and incident-recovery procedure](operations.md) before restoring real data. Stop the app **and optional overlays**, ensure the backup is available inside the volume, then for the single-service installation:

```bash
docker compose stop
docker compose run --rm --no-deps --entrypoint python spoolmera \
  scripts/restore.py /data/backups/before-upgrade.sqlite3 \
  /data/spoolmera.sqlite3 --confirm
docker compose up -d
```

Restore checks schema, identity, integrity and manifest where present, then performs the real upgrade and current table/column checks on its staging copy before replacement. It rejects active database use and preserves existing bytes. Crash sidecars can require deliberate quarantine: **never remove a live WAL file**. Restoring revokes browser sessions and machine tokens; sign in and reissue tokens, then inspect any uncertain physical printer operations. Do not perform an untested restore directly against your only copy of inventory.

## Isolated test instance

Run `python3 scripts/start_test.py` from the repository root to start a separate environment on **127.0.0.1:8766** with its own data volume. No hardware/printer access is enabled by default. Browser/HTTP smoke scripts create data and must **never** run against a production installation. See [Testing](testing.md).

## Availability and request budgets

The default image admits at most 64 concurrent Uvicorn connections/tasks, and Compose
sets a 768 MiB memory ceiling for the main container. Public setup/login JSON is
limited to 4 KiB at the ASGI transport boundary, including streamed requests.
Login work is additionally limited by atomic per-client and instance-wide rolling
budgets and at most four simultaneous password verifications. Reverse proxies
and VPN gateways should independently restrict request size, concurrent clients
and authentication attempts; **do not** trust arbitrary `X-Forwarded-For` headers
as a substitute for a configured trusted proxy. NAT or reverse-proxy clients may
share one peer-address login budget. Budget exhaustion returns HTTP 429; oversized
public authentication requests return HTTP 413.

Read-only metadata inspection runs bounded G-code and 3MF parsing off the API
event loop. Concurrent manual/background printer polling for the same device is
rejected or skipped rather than opening duplicate controller sessions. A manual
poll that is already active returns HTTP 429. These safeguards protect service
availability but do not replace container, ingress, device-network and host
resource controls.
