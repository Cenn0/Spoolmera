# Spoolmera

<img src="frontend/public/spoolmera-wordmark.svg" alt="Spoolmera — Your 3D Printing Workspace" width="440">

**Your 3D Printing Workspace.** A free, self-hosted workspace for filament inventory, physical spools, printers and print jobs.

[![Apache License 2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
![Status: experimental](https://img.shields.io/badge/status-experimental-orange)
![UI languages: EN / DE](https://img.shields.io/badge/UI-English%20%7C%20Deutsch-167d75)
![Deployment: Docker](https://img.shields.io/badge/deployment-Docker-2496ED)
[![CI](https://github.com/Cenn0/Spoolmera/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Cenn0/Spoolmera/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Cenn0/Spoolmera/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Cenn0/Spoolmera/actions/workflows/codeql.yml)

> **Fully AI-developed, human-engineered.** This is an experiment in AI-led software development: AI produces implementation and initial documentation while a human defines requirements, makes engineering decisions, reviews results and remains responsible for operation. Tests cover specific behavior; they do **not** guarantee security, hardware compatibility or production readiness.
>
> **Project status:** experimental v0.10.0, Apache-2.0 source code in the **public** [Spoolmera repository](https://github.com/Cenn0/Spoolmera). It is not a hosted product or a published stable release. CI artifacts on `main` are temporary test builds, not signed official releases.

## Filament products at a glance

The **Filaments** view groups products by material, color and variant. Its cards show how much stock is available **across the physical spools** belonging to each product, flag low stock and link directly to the matching rolls. This makes it useful for choosing a filament *before* checking which specific spool to use.

<a href="docs/screenshots/filaments-dark.png">
  <img src="docs/screenshots/filaments-dark.png" alt="Spoolmera filament catalog: six example filament products with color previews, available material and links to their physical spools" width="900">
</a>

*Filament catalog · dark mode. Screenshot from the real Angular app with synthetic German-language test data; [view at full resolution](docs/screenshots/filaments-dark.png).*

## What you can do

| Area | Current capabilities |
| --- | --- |
| **Filament catalog** | Case- and accent-insensitive multi-term search; products with brand, material, color, diameter, density, temperature limits, product IDs and reorder thresholds; optional review-first community catalog lookups |
| **Physical spool inventory** | Individual UUIDs, tare/remaining weight, purchase details, location, condition, opening/archive state, drying records, low-stock flags |
| **Inventory UX** | Color-coded cards and table view, filters, storage board, label tray, drag-and-drop with keyboard/click alternatives, light/dark/system themes |
| **Accounting** | Transactional movements, manual weighing, actual/partial/zero-use job review, traceable corrections and a searchable history |
| **Labels and migration** | QR labels (60 × 40 / 50 × 30 mm), batch spool registration, validated CSV import/export and create-only Spoolman JSON snapshot import |
| **Print jobs** | Job tracking, G-code/3MF metadata inspection, explicit multi-tool-to-spool mappings, advisory reservations and optional Bambu task-correlated estimated consumption |
| **Printer connections** | Local Moonraker/Klipper, OctoPrint and **experimental community Bambu Lab LAN MQTT** integration (capabilities differ; see below) |
| **Optional operations** | Privileged printer commands, G-code file transfer for supported controllers, isolated PrusaSlicer STL slicing, signed cloud/scale event bridges, scoped read-only automation tokens and notification sidecar |
| **Administration** | First-run administrator setup, viewer/editor/admin roles, diagnostics, SQLite backup and guarded offline restore |
| **Languages** | English and German across the UI and printable labels, with browser-saved language selection |

**Safety boundary:** A registered print job, logical printer-slot assignment, imported metadata, advisory reservation or signed cloud event does **not** by itself deduct stock or start a physical print. Auto-accounting is deliberately restricted; ambiguous outcomes need operator review.

## Quick start: one Docker container

**Requirements:** Docker Engine or Docker Desktop with Docker Compose; Git access to this repository. No cloud account, paid subscription or external database is needed. The default build compiles Angular and packages the resulting static frontend with the Python/FastAPI server.

```bash
git clone https://github.com/Cenn0/Spoolmera.git
cd Spoolmera
cp .env.example .env

# Generate a unique secret; copy its output into SPOOLMERA_BOOTSTRAP_TOKEN in .env
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'

docker compose up -d --build
```

Open **http://127.0.0.1:8765** on the Docker host and create the first administrator using the bootstrap token and a password of **at least 14 characters**. There is no default admin account. An empty or missing bootstrap token blocks initial setup.

```bash
docker compose ps
docker compose logs -f spoolmera
# Stop without deleting saved data:
docker compose down
```

The database persists in the Docker volume `spoolmera_data`. **Never run `docker compose down -v` unless you intend to delete your data.** Take a verified SQLite backup before upgrades.

### Access from other devices

By default the app binds to `127.0.0.1:8765`, deliberately **not** the public network. For other devices, configure an **HTTPS reverse proxy or trusted VPN** and set in your private `.env`:

```dotenv
SPOOLMERA_PUBLIC_BASE_URL=https://spoolmera.example.com
SPOOLMERA_COOKIE_SECURE=1
```

Configure your proxy and network separately. Do not expose the application's HTTP login or printer interfaces directly to the internet. `SPOOLMERA_PUBLIC_BASE_URL` must be the actual externally reachable **origin**, without a path; it also determines QR-label links. Using `127.0.0.1` on a phone points to the phone itself, not your server.

More detail: [installation, upgrade and backups](docs/deployment.md) · [security and printer configuration](docs/security-and-printers.md).

### Optional services (off by default)

The primary application remains **one runtime container**. Features requiring additional isolation use separate opt-in Compose overlays:

```bash
# Optional, isolated STL slicing worker (requires profile directory and worker token)
docker compose -f compose.yaml -f compose.slicer.yaml up -d --build

# Optional notification sidecar (requires its own scoped token/notification settings)
docker compose -f compose.yaml -f compose.notifications.yaml up -d --build
```

Configure these components before starting them. See [operator procedures](docs/operations.md); neither overlay is needed for inventory management.

## Supported interfaces vs. tested behavior

| Integration | Implemented behavior | Support / verification boundary |
| --- | --- | --- |
| **Moonraker / Klipper** | Status polling; opt-in file upload, start/pause/resume/cancel; constrained completion-based estimated accounting | Upstream HTTP interfaces documented; tested with simulated controllers. **No physical printer certified** |
| **OctoPrint** | Status polling; opt-in G-code transfer and commands; completion remains manual review | Upstream HTTP interfaces documented; tested with simulated controllers. **No physical printer certified** |
| **Bambu Lab LAN MQTT** | LAN status, temperature/progress, AMS observations; optional pause/resume/stop and per-job **opt-in estimated stock debit** after task ID + filename are observed from RUNNING to FINISH | **Community / non-official adapter**; no vendor-guaranteed completion history, requires compatible firmware and pinned TLS certificate. No native cloud, upload, remote start or hardware certification |
| **Cloud event ingestion** | HMAC-authenticated events for an operator-provided bridge; untrusted job outcomes move to review | Vendor-neutral contract only; **no native vendor cloud connector** |
| **PrusaSlicer CLI** | Operator-approved STL-to-G-code conversion inside an opt-in worker | Application-level integration; no guarantee that emitted G-code is safe for a real device |

**Implemented ≠ officially supported ≠ best practice ≠ security certified.** Controller compatibility varies with firmware, access settings and hardware. Enabling physical commands (`SPOOLMERA_PRINTER_CONTROL_ENABLED=1`) is an explicit operator decision, not the recommended default. Use least-privilege credentials, exact private-IP allowlists, TLS where applicable and supervised first prints. The Bambu LAN adapter is documented in [Security and printers](docs/security-and-printers.md).

Not implemented: native Bambu/Prusa cloud login and control, OIDC/SSO, automatic AMS-to-physical-spool mapping, general USB load-cell drivers, universal OpenPrintTag payload decoding or complete Spoolman API compatibility. Browser NFC availability is device-dependent.

## Working with physical spools

### Each roll has its own identity

A filament *product* can have multiple physical rolls. In **Spools**, you see each roll's material and color, remaining weight, condition and storage location. Search ignores case and common accents (for example `Grun` matches `Grün`) across product and roll details, while filters and pagination narrow the inventory; a card or table view provides different levels of detail. Consumption, weighing and corrections are recorded against the **individual spool**, not an entire product group.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/spools-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/screenshots/spools-light.png">
  <img src="docs/screenshots/spools-light.png" alt="Physical spool inventory showing individual color-coded rolls, remaining weights, stock status and filters" width="900">
</picture>

*One inventory, two appearances: the screenshot switches between light and dark with your browser color-scheme preference. Open the [light screenshot](docs/screenshots/spools-light.png) or [dark screenshot](docs/screenshots/spools-dark.png) at full resolution.*

### Locate spools without changing stock

Switch the inventory to **Locations** to see physical rolls grouped by their recorded storage place. The board uses the full inventory width, fits complete location columns to the available space and stacks them on phones. Each column follows its own contents, so empty locations remain compact. Reassign a roll by dragging it or choosing a destination; saving the new location still requires explicit physical confirmation.

<a href="docs/screenshots/locations-dark.png">
  <img src="docs/screenshots/locations-dark.png" alt="Spoolmera Locations board grouping example filament rolls by storage area and showing their assigned locations" width="800">
</a>

*Storage location board · dark mode. [View the complete screenshot](docs/screenshots/locations-dark.png).*

### Use the inventory next to your printer

The same responsive web interface works in a narrow mobile browser: key stock figures, search, filters and spool cards remain accessible, while secondary navigation moves into a compact menu. There is no separate mobile app or additional service to install.

<a href="docs/screenshots/spools-mobile-dark.png">
  <img src="docs/screenshots/spools-mobile-dark.png" alt="Spoolmera mobile spool inventory at 390-pixel viewport width, with stock summary, filters, first spool card and bottom navigation" width="290">
</a>

*Mobile spool inventory · 390 × 844 browser viewport. [View the original screenshot](docs/screenshots/spools-mobile-dark.png).*

### Continue from inventory to print preparation

- **Identify each spool:** Print its own **60 × 40 mm** or **50 × 30 mm QR label**. The QR URL stays tied to that physical spool as its weight changes; printed weight is only a snapshot. The label tray lets you select and reorder up to 100 rolls.
- **Move existing data:** Export or preview/import the versioned CSV format. Existing UUIDs are skipped rather than overwritten; CSV is **not** a complete backup. Spoolman JSON imports are snapshot-based, not live synchronization.
- **Track printing:** Register a print job and deliberately map each extruder tool to a physical spool. Imported G-code/3MF provides metadata, not automatic printer instructions. Bambu jobs can explicitly opt into automatic debit of **slicer-estimated**, not weighed, grams after a correlated MQTT completion; failures and uncertain results always require manual review. Check estimates, actual stock and uncertainty before authorizing physical actions or accounting.

All images on this page come from the passing [Chromium CI browser run](https://github.com/Cenn0/Spoolmera/actions/runs/38064112965) with disposable sample data and no connected printer. [Image sources and regeneration instructions](docs/screenshots/README.md) · [CSV schema](docs/csv-format.md) · [UI controls](docs/interface-ux.md) · [language behavior](docs/interface-languages.md) · [print operations](docs/operations.md).

## Architecture at a glance

```text
Browser (Angular 22, English/German, light/dark)
                       |
                 same-origin HTTP
                       |
FastAPI modular monolith (Python 3.12 / SQLite)
  ├─ Auth, users, inventory, movement ledger, REST API
  ├─ Print job state, reconciliation, printer adapters
  ├─ Controlled backup/restore and diagnostics
  └─ Persistent Docker volume: /data/spoolmera.sqlite3

Optional, independently enabled:
  ├─ Isolated PrusaSlicer worker (no DB or printer credentials)
  └─ Notification bridge sidecar
```

A single FastAPI process per SQLite database is the supported deployment. There is no required broker, Kubernetes cluster, hosted API or Node.js runtime in the production image. See [Architecture](docs/architecture.md) for transaction invariants, module boundaries and failure handling.

## Develop and verify

Backend: **Python 3.12**. Frontend: **Angular 22**, with a Node.js version compatible with `frontend/package.json` (Node 24.15+ supported). Install from the committed hash/lockfiles:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt

# In terminal 1, after setting a unique SPOOLMERA_BOOTSTRAP_TOKEN:
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765

# In terminal 2:
cd frontend
npm ci
npm start
# Browser development URL: http://127.0.0.1:4200
```

Tests and build:

```bash
python -m pytest -q
python scripts/generate_api_types.py --check
cd frontend
npm run typecheck
npm run i18n:check
npm test
npm run build
```

The CI pipeline additionally runs Docker, browser, migration/recovery, opt-in worker and dependency checks. Hardware tests use synthetic controller responses unless explicitly stated; CI success does not imply production certification. Read [Testing](docs/testing.md) and [reproducible build inputs](docs/build-reproducibility.md).

## Documentation

Start with the [documentation index](docs/README.md), which separates **current operating guides** from **dated implementation/review records**.

- [Deployment, configuration and upgrades](docs/deployment.md)
- [Interface and interactions](docs/interface-ux.md) · [English/German UI](docs/interface-languages.md)
- [Printer control and optional services](docs/operations.md) · [Integrations](docs/integrations.md)
- [Security model and printer restrictions](docs/security-and-printers.md) · [Security policy](SECURITY.md)
- [Architecture](docs/architecture.md) · [feature and limitation matrix](docs/roadmap-implementation.md)
- [Testing and evidence](docs/testing.md) · [Screenshot provenance](docs/screenshots/README.md)
- [Contributing](CONTRIBUTING.md)

## License and contributions

Spoolmera is an **Apache License 2.0** project. See [LICENSE](LICENSE). Individual third-party packages and services retain their upstream terms. Development contributions, bug reports and critical reviews are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). The repository is public; security issues must be reported privately as described in [SECURITY.md](SECURITY.md). Pull requests are checked by CI and CodeQL.
