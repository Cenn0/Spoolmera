
# Feature expansion: Spoolmera v0.10.0 (experimental)

This release remains fully free, Apache-2.0-licensed, Docker-self-hosted and based on Angular, Python/FastAPI and SQLite. The default installation is a single application container. No cloud account, paid service or vendor API is required.

## Delivered feature matrix

| Capability | What is implemented | Primary source |
| --- | --- | --- |
| Rich material properties | Density, nozzle/bed limits, GTIN/SKU, slicer preset, low-stock threshold | app/models.py |
| Physical spool metadata | Tare, purchase price/currency/date, batch and location | app/models.py |
| Filament catalog search | Local multi-term filtering across product details, insensitive to case and accents without modifying stored product data | frontend/src/app/features/filaments/product-view.ts |
| Physical spool search | Server-side Unicode casefolding and accent-insensitive literal substring search across product/spool fields, with existing cursor pagination and filters | app/services/inventory_query_service.py |
| Responsive inventory | Cards, full-width tables and location grids, independent lane heights, direct label selection and explicit physical-location confirmation | frontend/src/app/features/spools/ |
| Complete visual audit | All routes and declared interactive states in light/dark desktop/mobile layouts, screenshot gallery and strict completeness/layout checks | scripts/ui_visual_audit.py, docs/testing.md |
| Manual weighing | Revision-aware gross minus tare, pending-job guard and durable measurement anchors | app/services/material_service.py |
| Consumption reconciliation | Actual/partial/zero use, preserved estimates, idempotent review, linked corrections and measurement reconciliation | app/services/accounting_service.py |
| Material care | User-recorded drying temperature, duration and note | app/services/material_service.py |
| Community catalog | Optional Open Filament Database browser; fixed HTTPS origin and cache; user-review before saving | app/api/catalog.py |
| Spoolman migration | Create-only JSON spool snapshots with import preview, rollback and external-source ID mapping | app/api/spoolman_import.py |
| Print readiness | Per-tool availability, independent advisory reservations and explicit loaded spool slots | app/services/reservation_service.py |
| Bounded optional slicing | Explicit two-thread PrusaSlicer ceiling matching the Compose CPU quota, existing single-operation/deadline/isolation guards, real CLI CI smoke with failure diagnostics | app/slicing.py, .github/workflows/ci.yml |
| Slicer metadata | Limited read-only G-code and sliced 3MF per-tool usage metadata; no execution | app/services/gcode_metadata.py |
| NFC identifiers | Register and resolve optional NFC/OpenPrintTag/custom tag IDs; Web NFC serial lookup on compatible browsers | app/api/identifiers.py |
| Signed scale bridge | Pending HMAC-SHA256 device reports, deduplication, human approval and atomic stock movement | app/api/scale.py |
| Local automation | Per-scope read-only and revocable bearer tokens; paginated stock and movement feeds | app/api/automation.py |
| Notifications | Opt-in categories, minimal secret environment, separate ntfy authentication, durable condition deduplication and restore-epoch handling | scripts/notification_bridge.py |
| Price reporting | Recorded material use and purchase-price allocation, currencies kept separate | app/api/analytics.py |
| Recovery | Bounded online snapshots, schema/identity validation, retained corrupt bytes, runtime ownership and live-process exclusion | app/api/backup.py, scripts/restore.py |
| Backup verification and upgrade rehearsal | Offline CLI with versioned JSON reports; real forward migration and current table/column checks on a private copy shared with restore; rejected candidates preserve the target, and accepted candidates contain checkpointed data | app/services/recovery_service.py, scripts/verify_backup.py, scripts/restore.py |
| History and archive | Server pagination, combined filters and accent-insensitive multi-term search over movement details, source/actor/job/correction links, archived UUID lookup and audited reactivation | app/services/inventory_query_service.py |
| Full movement-history CSV export | Same server filters as history page, all matching archived/current ledger entries independent of pagination, versioned UTF-8/CRLF spreadsheet-safe streaming from one SQLite read snapshot, viewer-accessible download | app/services/movement_csv_service.py, app/api/inventory.py, frontend/src/app/features/history/ |
| Batch registration and labels | Atomic 1–100 roll creation, immutable preview, durable retries and one UUID/label per roll in both 60 x 40 mm and 50 x 30 mm formats | app/services/inventory_query_service.py, app/labels.py |
| Restock | Product targets, active physical stock, zero-stock products and separately displayed reservations | app/services/inventory_query_service.py |
| Operations | Supervised worker/lease state, device failures, unresolved commands/uploads, storage, backup and recovery diagnostics | app/api/diagnostics.py |
| Bambu Lab LAN (experimental) | Community/non-official MQTT observations and AMS/status telemetry, opt-in pause/resume/stop, pinned TLS certificate; no upload, remote print start or vendor-cloud authentication | app/infrastructure/printers/bambu.py |
| Registry image acceptance | Digest-pinned downloads on native AMD64/ARM64 runners, source/user/asset checks, authenticated HTTP/restart/offline recovery, actual-image vulnerability/SBOM gate and freshness recheck before main promotion; blocking upstream package findings remain open | scripts/verify_published_image.py, scripts/scan_container.py, .github/workflows/publish-main-image.yml |
| Experimental release integrity | Release workflow packages the tested amd64 image with nested and outer SHA-256 manifests; an offline, extraction-free verifier rejects inconsistent archive paths, content and release source identity before GHCR/Release publication | scripts/verify_release_bundle.py, .github/workflows/release-test.yml |

## Operational invariants

1. Physical balances are changed only in SQLite write transactions with a linked movement ledger entry. Physical scale reports, external cloud receipts, reservations, speculative material mappings and slicer estimates do not independently debit inventory.
2. Reserving a job is advisory: other print operations can still make the reserved quantity insufficient. Recheck physical stocks and printer safety before printing.
3. Tags are **identifiers, not authentication**. Bluetooth/USB readers and Web NFC are optional; QR works without browser NFC.
4. Human review of a signed scale report applies its movement and records event disposition atomically; repeat/replayed events cannot apply additional consumption.
5. Spoolman import never overwrites a known external ID. It does not reconstruct imported movement history or archive status.
6. All automation tokens are hashed in SQLite, restricted to one read-only scope, individually revocable and returned as plaintext only on creation.
7. External community catalog content is not authoritative machine configuration; product values must be reviewed by the user.
8. Backups contain credential hashes, tokens hashes and user inventory. Protect backup files and restore only with the service stopped.
9. Notification delivery is at least once. If delivery succeeds before state is persisted and the bridge crashes, a condition can be notified twice. It never controls a printer.

## Support and security classifications

- **Works at application level:** APIs, Angular workflows and regression cases tested in GitHub Actions. Passing tests are not a declaration of production readiness.
- **Documented upstream interfaces:** Moonraker and OctoPrint HTTP APIs, and the Open Filament Database published static JSON endpoints. Their existence does not certify specific printer firmware.
- **Recommended operating model:** A single FastAPI runtime worker and SQLite volume, local HTTPS reverse proxy or VPN, no required cloud or paid services.
- **Security recommendation:** Leave physical printer control and slicing disabled by default, use private-IP allowlists and restricted credentials, never trust unverified hardware events to modify inventory.
- **Not delivered or verified:** Native Bambu/Prusa vendor-cloud login and control, universal Web NFC, OpenPrintTag NDEF payload parsing, arbitrary USB/ESPHome firmware drivers, OIDC/SSO, direct live Spoolman API emulation, and physical printer certification. These require tested vendor/provider infrastructure and cannot be honestly claimed via simulated responses.

## Remaining roadmap and dependencies

| Order | Remaining acceptance item | Implemented automation | Still required |
| --- | --- | --- | --- |
| 1 | Actual container-package vulnerability acceptance | Full image inventory and CycloneDX SBOM; fail-closed HIGH/CRITICAL gate, including unfixed findings, before main promotion/versioned release | Resolve currently reported upstream OS package findings; a candidate is not accepted merely because source CI passes |
| 2 | Accepted registry image on both CPU architectures | Pull exact GHCR digest on native AMD64/ARM64; source/user/assets, HTTP, ledger/restart and offline recovery checks | Successful registry verification **after item 1 passes** on the revision being installed |
| 3 | Independently downloaded versioned release / package upgrade | Existing tagged bundle build, checksums and offline verifier; actual release-image scan now gates publication | An unused reviewed version tag, completed release job, and download/upgrade verification on a separate host; no published GitHub release existed at this review |
| 4 | Real printer/firmware, interruption and spool-change evidence | Simulated controller regression suite and public hardware report procedure | Authorized supervised physical test evidence and review |
| 5 | Calibrated scales, NFC/tag readers and complete cost accuracy | Signed-event/identifier regression coverage | Physical devices, calibration/measurement uncertainty and recorded results |
| 6 | Independent security acceptance | Source CI/CodeQL, dependency audits and new actual-image scan | An independent review; automated checks are not equivalent |

The code-side registry/release gates are implemented. These acceptance items are **not all complete**, and hardware/provider capabilities listed as not delivered above are not silently promoted to supported features.

## Before stable 1.0

- Validate multiple real printer/firmware combinations, job interruption and spool changes.
- Verify sensor calibration, NFC/physical tag readers and full print cost accuracy on real hardware.
- Native Linux arm64 CI now builds the default application image and exercises authenticated HTTP, ledger persistence across restart and guarded offline restore; the gate must pass on the actual revision before treating it as verified. Validate additional released-package upgrades and real deployment hosts before claiming arm64 release support.
- Historical-schema fixtures now exercise migration and restoration through the current initializer, including the Docker recovery path. These are software regression checks, not evidence of an upgrade between independently downloaded release packages or of recovery on every deployment host; those checks remain open.
- The [hardware compatibility matrix](hardware-compatibility.md) now publicly separates simulated software coverage from unverified hardware. **Real printer/firmware combinations, sensor calibration and physical operation remain unvalidated**; collect and review supervised evidence before any compatibility claim.
- Complete an **independent** security review; existing CI/CodeQL and the new matrix are not substitutes for external security acceptance.
- Execute the versioned release workflow against an unused tag and verify downloaded ZIP/registry artifacts on a separate host; a green PR CI alone does not verify GHCR availability or release publication. Checksums are not signatures and do not constitute an independent supply-chain security review.

This document describes the code, not completion of these external release prerequisites.

See [the review implementation and evidence](implementation-2026-10-09.md) for the current change and the distinction between application tests, simulated controllers and hardware validation.
