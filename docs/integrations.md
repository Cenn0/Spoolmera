# Printer and slicer integration — contract and roadmap

**Status: foundation only. There is no active printer or slicer connector.**

The goal is to make Filament Manager useful for a variety of printer ecosystems without binding the inventory schema to any single vendor or requiring remote printer access from the inventory service.

## Implemented read-only API v1

\`GET /api/integrations/v1/capabilities\`:

\`\`\`json
{
  "schema_version": "1",
  "inventory_read": true,
  "usage_write": false,
  "printer_connections": false,
  "slicer_connections": false
}
\`\`\`

\`GET /api/integrations/v1/spools\`:

\`\`\`json
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
\`\`\`

Values above are illustrative and not actual API contents. Identifiers are immutable per physical spool. The endpoint returns active spools only. The schema is versioned so future adapters can distinguish incompatible changes.

**Security:** This API currently has the same protections (or lack thereof) as the local application. It is not safe to publish externally without strong authentication and transport security.

## Proposed adapter boundary (not implemented)

A future adapter should run as a separate module or process, depending on printer credentials and network trust. Its responsibilities could include:

1. Discovering configured printers or slicers using their **official, version-matched** interfaces.
2. Matching spool UUIDs to printer feeder slots or slicer presets using explicit user approval; never assume a match by color alone.
3. Obtaining *estimated* consumed material from completed jobs, distinguishing slicer predictions from measured values.
4. Presenting proposed stock deductions for user approval until safe automation can be validated.
5. Emitting authenticated, idempotent usage events with unique per-source event IDs, so reconnection and retries cannot double-subtract a spool.
6. Treating interrupted jobs, purge/wipe material, multi-material prints, failed prints, and spool swaps as explicit edge cases.

An **illustrative, future-only** event shape (there is no route accepting this payload yet):

\`\`\`json
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
\`\`\`

Before enabling write integration, add a persistent unique constraint on \`(source, event_uid)\` and implement the event insert plus inventory deduction in the **same transaction**, with retry-safe responses.

## Integration candidates to evaluate later

Potential adapter targets include OctoPrint, Moonraker/Klipper, Bambu Lab, Prusa Connect, and common slicer project or metadata formats. These are **candidates**, not verified compatible or officially supported integrations. Check each product's current official documentation, authentication model, licensing, and supported API versions when choosing an adapter.

## Recommended delivery order

1. Explicit printer-to-spool assignments and controlled settings storage.
2. Source-specific read-only adapters and completion/event telemetry.
3. Manual review and approval of estimated consumption.
4. Authenticated event-ingestion API with auditability and idempotency.
5. Optional automated deduction only after extensive failure-mode testing.

Printers and slicers should never be able to execute arbitrary operations on the inventory host.
