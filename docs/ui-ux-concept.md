# Angular UI/UX concept — Material Workspace

> Status: Approved implementation baseline for the Angular migration.
>
> User-facing interface language: **English**. The repository remains Apache-2.0 licensed.

## Goals

A self-hosted, mobile-friendly inventory workspace with clear separation between filament **products** (brand, type, color, diameter) and physical **spools** (remaining stock, status, location, movements, stable QR UUID). Optimize for common operations rather than charts or decorative dashboard widgets.

## Information architecture

- **Overview** — stock KPIs, low-stock queue, material distribution, recent movements.
- **Spools** — responsive inventory with search, material/status filters, remaining-weight bars, consumption, label and detail actions.
- **Filaments** — reusable product catalog, editing and adding individual spools.
- **History** — chronological, read-only inventory ledger.
- **Integrations** — accurate read-only API capabilities and explicitly *not connected* printer/slicer status.

## Visual system

- Warm, low-glare off-white work area (`#F6F7F4`), white panels and subtle graphite borders.
- Dark graphite-blue navigation (`#172B32`) and neutral typography, with muted teal (`#227B70`) for primary actions, amber (`#D5A14F`) for attention, and terracotta (`#C26756`) only for destructive intent.
- Distinguish product color swatches from functional status colors; no arbitrary marketing gradients or glass effects.
- System font stack only (no external CDN); consistent 8px-based spacing, visible keyboard focus, WCAG-conscious contrast and touch targets.

## Key user journeys

1. **First use:** empty overview → create product → register a spool → show physical spool inventory.
2. **Record use:** scan QR or open spool → choose consumption → positive whole grams → server transaction → refresh stock/history only after success.
3. **Correct stock:** choose adjustment → signed whole grams and mandatory reason → server validates capacity and commits ledger.
4. **Inventory transfer:** export CSV or choose file → dry-run preview → explicit confirmation → create-only import; no updates to existing UUIDs.
5. **Print label:** use stable spool UUID label endpoint in a new tab; QR payload must use configured reachable base URL.
6. **Archive:** explicit destructive-action confirmation; preserve movement history.
7. **Deep links:** `/s/{uuid}` redirects to `/?spool={uuid}`; startup resolves and opens active spool or clearly says unavailable.

## Responsive design

Desktop ≥ 1024px: fixed side navigation, title/actions toolbar, dense but readable data tables.
Tablet 640–1023px: compact sidebar, scrolling tables with explicit action labels.
Mobile < 640px: compact header with horizontal/bottom navigation, spool cards instead of clipped table rows, large direct actions and modal panels.

## Accessibility and reliability

- Semantic landmarks, labels, descriptive buttons, visible focus states, meaningful feedback with `role="status"`/`role="alert"`, keyboard-operable dialogs.
- Do not imply connectivity/authentication: no auth exists. Instance remains bound to loopback by default.
- Keep the Python FastAPI/SQLite API and exact stock-ledger invariants; no frontend-only or speculative inventory updates.
- Distinguish loading, empty, filter-empty, failure and success.
- Production image builds and serves *static Angular assets* from the existing Python container, using a multi-stage Docker build. No separate browser-facing Node service.
- Angular standalone + router + typed HTTP service + signal-based state, with no external frontend runtime/CDN.

## Acceptance criteria

- Existing backend endpoints, QR printing and CSV exchange still work.
- All existing user workflows implemented in Angular, no vanilla-JS duplicate shell.
- Deep links and refreshable application routes work.
- CI builds Angular, tests Python API and exercises browser workflows; Docker smoke validates served assets.
- Document limitations: no auth, printer/slicer connection or automatic consumption.
