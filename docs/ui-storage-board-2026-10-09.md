# Storage board and stock-health UI review (October 9, 2026)

## Verified starting point

PR #8 head `3cc507f` already implements light/dark/system themes, bilingual labels, responsive inventory cards, material product galleries and sorting, filename drops, a reorderable label tray and printer-slot staging. CI run #114 passes all five jobs. The real CI screenshots show consistent dark desktop and mobile views. Those elements were retained.

Two operational usability gaps remained: existing spool views could not be sorted by remaining weight or storage location, and there was no visual location organization or safe drag-and-drop storage workflow. Product totals had no explicit progress against their configured restock targets.

## Changes and safeguards

- **Spools**: add persisted per-browser sorting of loaded rows by name, location, remaining weight, or original API order. No server writes or data mutation occur when sorting. The view selector now offers **Locations** as a third layout.
- **Storage board**: locations are derived from real spool records; editors may create a temporary new lane. An empty lane has no database record and is not advertised as persistent. A future location persists only when a spool is assigned.
- **Drag and drop**: editor moves a spool to a target lane, or uses a per-spool destination selector. Both prepare a confirmation panel only; a drop never directly writes. Archived spools and viewers cannot modify location.
- **Physical verification**: the operator must check the actual physical storage location and explicitly confirm before saving. The UI does not claim a physical reel moved automatically.
- **Concurrent edit protection**: a successful API read first verifies the spool and its original location. The PATCH carries an optional `expected_location`, compared against current SQLite state inside the same write transaction; stale location changes return HTTP 409 without changing any data. Existing clients omitting the precondition remain backward compatible.
- **Uncertain outcomes**: no automatic retry of a failed location PATCH. On network failure the pending change is cleared and inventory refreshed. A successful change is audited; stock weights, reservations and print accounting are unaffected.
- **Product stock health**: show a compact progress indicator against `target_stock_g` when configured, a threshold warning and an accessible progress value. The bar caps at 100%, while the actual weight remains unchanged.
- **Accessibility**: selects and confirmation buttons provide keyboard alternatives for each drop. The board has an identifiable scroll region; contrast uses current semantic theme tokens. Both English and German have matching text.

## Known limitations

The board operates on the currently loaded, server-filtered page and says so explicitly; it does not pretend unloaded spools are present. Locations are text labels, not separately managed storage entities. Each confirmed move is a single-spool update; no batch transaction is implied. Physical storage and actual printer slots remain operator-controlled.

## Acceptance tests

- Backend: conditional and legacy updates, stale conflict and archived/invalid rejection, no ledger/stock changes and one audit record per confirmed update.
- Pure frontend: deterministic sorts and lane grouping including empty locations.
- Angular UI: editor/viewer permissions, staging before saving, physical verification gate, stale responses and no retry of uncertain writes.
- Browser: real drag/drop, confirmation and server persistence; EN/DE, dark mode and mobile scroll regression. The normal Docker, dependency and slicer gates stay intact.
