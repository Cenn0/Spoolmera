# Printer and slicer integration — contract and roadmap

**Status: the v1 inventory API remains read-only; separate authenticated Moonraker and OctoPrint connectors support optional commands and file upload, approved-profile PrusaSlicer CLI slicing, explicit tool mappings and an HMAC-signed cloud event bridge.** All write/physical operations are opt-in and documented in [Operations](operations.md).

The goal is to make Filament Manager useful for a variety of printer ecosystems without binding the inventory schema to any single vendor or requiring remote printer access from the inventory service.

## Implemented read-only API v1

`GET /api/integrations/v1/capabilities`:

```json
{
  "schema_version": "1",
  "inventory_read": true,
  "usage_write": false,
  "printer_connections": false,
  "slicer_connections": false
}
```

`GET /api/integrations/v1/spools`:

```json
{
  "schema_version": "1",
  "spools": [
    {
      "spool_uid": "930ff9ed-0d12-4124-8e28-39d21cdd47b2",
      "product_uid": "58b52341-f3cf-481e-887e-5a4ae5ea5a72",
      "brand": "Example Filament",
      "product_name": "Basic",
      "material": "PLA",
      "color_name": "Black",
      "color_hex": "#222222",
      "diameter_mm": 1.75,
      "initial_g": 1000,
      "remaining_g": 750,
      "opened": true,
      "location": "Shelf A"
    }
  ]
}
```

Values above are illustrative and not actual API contents. Identifiers are immutable per physical spool. The endpoint returns active spools only. The schema is versioned so future adapters can distinguish incompatible changes.

**Security:** The v1 read-only inventory endpoints require an authenticated application session and must be accessed over trusted transport. The v1 capability flags describe only the external v1 API contract, **not** availability of the separate admin-configured printer connectors.

## Future outbound event/mutation contract (not implemented)

The new read-only controller connectors and job tracker are documented in [Security and printer operation](security-and-printers.md). A separate future write-event adapter could run as a module or separate process, depending on network trust. Potential responsibilities include:

1. Discovering configured printers or slicers using their **official, version-matched** interfaces.
2. Matching spool UUIDs to printer feeder slots or slicer presets using explicit user approval; never assume a match by color alone.
3. Obtaining *estimated* consumed material from completed jobs, distinguishing slicer predictions from measured values.
4. Presenting proposed stock deductions for user approval until safe automation can be validated.
5. Emitting authenticated, idempotent usage events with unique per-source event IDs, so reconnection and retries cannot double-subtract a spool.
6. Treating interrupted jobs, purge/wipe material, multi-material prints, failed prints, and spool swaps as explicit edge cases.

An **illustrative, future-only** direct inventory usage-write event shape (there is no route accepting this payload; the separate cloud receipt route only records events and marks needs_review):

```json
{
  "schema_version": "1",
  "source": "example-adapter",
  "event_uid": "a7f186da-4c7a-4266-93ea-f9ab9b4b92b0",
  "spool_uid": "930ff9ed-0d12-4124-8e28-39d21cdd47b2",
  "job_uid": "my-printer-job-123",
  "consumed_g": 37,
  "measurement": "estimated",
  "status": "completed"
}
```

Before enabling write integration, add a persistent unique constraint on `(source, event_uid)` and implement the event insert plus inventory deduction in the **same transaction**, with retry-safe responses.

## Integration candidates to evaluate later

OctoPrint and Moonraker/Klipper adapters now include optional physical control, G-code transfer, and tracked-job start, tested against mock transport only (not live hardware certification). Bambu Lab LAN-only MQTT (read-only observations and opt-in pause/resume/stop) is implemented with strict TLS certificate pinning; Bambu Lab and Prusa Connect **native cloud APIs are not implemented**; approved operator cloud bridges can send signed status receipts to the generic webhook. Full vendor compatibility remains unverified. Check each product's current official documentation, authentication model, licensing, and supported API versions when choosing an adapter.

## Future delivery order

1. Harden controller history capture, device compatibility testing and recovery from missed polling.
2. Expand existing explicit multi-extruder spool mapping to slicer-derived per-tool quantities and optional waste estimates.
3. Add authenticated, idempotent source-event ingestion with a separate durable scheduler.
4. Harden existing opt-in printer control and slicing for verified hardware profiles and more isolated execution.

Printers and slicers should never be able to execute arbitrary operations on the inventory host.
