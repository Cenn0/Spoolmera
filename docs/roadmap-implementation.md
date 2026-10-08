
# Feature expansion: FilamentManager v0.9 (experimental)

This release remains fully free, Apache-2.0-licensed, Docker-self-hosted and based on Angular, Python/FastAPI and SQLite. The default installation is a single application container. No cloud account, paid service or vendor API is required.

## Delivered feature matrix

| Capability | What is implemented | Primary source |
| --- | --- | --- |
| Rich material properties | Density, nozzle/bed limits, GTIN/SKU, slicer preset, low-stock threshold | app/models.py |
| Physical spool metadata | Tare, purchase price/currency/date, batch and location | app/models.py |
| Manual weighing | Gross minus empty spool tare, movement ledger and audit, no double adjustment | app/services/material_service.py |
| Material care | User-recorded drying temperature, duration and note | app/services/material_service.py |
| Community catalog | Optional Open Filament Database browser; fixed HTTPS origin and cache; user-review before saving | app/api/catalog.py |
| Spoolman migration | Create-only JSON spool snapshots with import preview, rollback and external-source ID mapping | app/api/spoolman_import.py |
| Print readiness | Per-tool availability, independent advisory reservations and explicit loaded spool slots | app/services/reservation_service.py |
| Slicer metadata | Limited read-only G-code and sliced 3MF per-tool usage metadata; no execution | app/services/gcode_metadata.py |
| NFC identifiers | Register and resolve optional NFC/OpenPrintTag/custom tag IDs; Web NFC serial lookup on compatible browsers | app/api/identifiers.py |
| Signed scale bridge | Pending HMAC-SHA256 device reports, deduplication, human approval and atomic stock movement | app/api/scale.py |
| Local automation | Per-scope read-only and revocable bearer tokens; paginated stock and movement feeds | app/api/automation.py |
| Notifications | Opt-in, separately isolated ntfy-compatible polling adapter with durable cursor | scripts/notification_bridge.py |
| Price reporting | Recorded material use and purchase-price allocation, currencies kept separate | app/api/analytics.py |
| Recovery | Admin-only SQLite online snapshot and stop-only restore with pre-restore backup | app/api/backup.py, scripts/restore.py |
| QR labels | Two print sizes: 60 x 40 mm and 50 x 30 mm | app/labels.py |

## Operational invariants

1. Physical balances are changed only in SQLite write transactions with a linked movement ledger entry. Physical scale reports, external cloud receipts, reservations, speculative material mappings and slicer estimates do not independently debit inventory.
2. Reserving a job is advisory: other print operations can still make the reserved quantity insufficient. Recheck physical stocks and printer safety before printing.
3. Tags are **identifiers, not authentication**. Bluetooth/USB readers and Web NFC are optional; QR works without browser NFC.
4. Human review of a signed scale report applies its movement and records event disposition atomically; repeat/replayed events cannot apply additional consumption.
5. Spoolman import never overwrites a known external ID. It does not reconstruct imported movement history or archive status.
6. All automation tokens are hashed in SQLite, restricted to one read-only scope, individually revocable and returned as plaintext only on creation.
7. External community catalog content is not authoritative machine configuration; product values must be reviewed by the user.
8. Backups contain credential hashes, tokens hashes and user inventory. Protect backup files and restore only with the service stopped.
9. The notification bridge is at-least-once, not a printer automation controller. If delivery occurs before the cursor update and the bridge crashes, an event can be notified twice.

## Support and security classifications

- **Works at application level:** APIs, Angular workflows and regression cases tested in GitHub Actions. Passing tests are not a declaration of production readiness.
- **Documented upstream interfaces:** Moonraker and OctoPrint HTTP APIs, and the Open Filament Database published static JSON endpoints. Their existence does not certify specific printer firmware.
- **Recommended operating model:** A single FastAPI runtime worker and SQLite volume, local HTTPS reverse proxy or VPN, no required cloud or paid services.
- **Security recommendation:** Leave physical printer control and slicing disabled by default, use private-IP allowlists and restricted credentials, never trust unverified hardware events to modify inventory.
- **Not delivered or verified:** Native Bambu/Prusa vendor-cloud login and control, universal Web NFC, OpenPrintTag NDEF payload parsing, arbitrary USB/ESPHome firmware drivers, OIDC/SSO, direct live Spoolman API emulation, and physical printer certification. These require tested vendor/provider infrastructure and cannot be honestly claimed via simulated responses.

## Before stable 1.0

- Validate multiple real printer/firmware combinations, job interruption and spool changes.
- Verify sensor calibration, NFC/physical tag readers and full print cost accuracy on real hardware.
- Exercise restore from prior schema versions and released packages on the intended amd64 and arm64 hosts.
- Complete an independent security review and publish hardware support matrices.
- Confirm no secrets exist in Git history and explicitly approve changing the private GitHub repository to public if an open-source community release is intended.

This document describes the code, not completion of these external release prerequisites.
