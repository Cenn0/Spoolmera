# Inventory interface and interaction model

The interface keeps English and German in one self-hosted Angular application. No external assets, translation services or new runtime dependencies are required for this UI revision.

## Appearance and navigation

The appearance control is available before sign-in and throughout the authenticated application. Choose **System theme**, **Light theme** or **Dark theme**. The initial choice follows `prefers-color-scheme`; an explicit choice is kept in browser local storage under `filament-manager-theme`. System changes and changes from another tab are reflected without reloading. Restricted browser storage falls back to an in-memory setting. This is a browser preference, not an account-wide server setting.

A same-origin, external `theme-init.js` sets the appearance before Angular starts, without relaxing the content security policy. Semantic surface, text, focus, border and status tokens cover forms, dialogs, tables, alerts, the login screen and feature pages. Filament swatches preserve their actual recorded colors; printed labels remain light and ink-friendly.

Desktop navigation is fixed to the top and scrolls independently. Narrow screens use an icon rail. Phones have three direct destinations and a **More** drawer for the remaining routes. The drawer supports Escape, focus containment, focus restoration and a backdrop. Resizing to desktop closes it. Main content has a skip link and enough bottom padding to scroll the last action above the mobile navigation. Document focus scrolling is immediate rather than animated, preventing the source from moving under the pointer while a native drag is being initiated.

## Spools and filament products

Spools default to color cards: material, color, physical roll identity, remaining weight, stock indicator, location and quick actions are visible together. **Cards / Table** is stored for the browser. Tables scroll in their own labeled region rather than forcing the page sideways. The optional NFC/scanner workflow is collapsed initially, leaving the inventory visible sooner. On phones, secondary import/export/batch actions are grouped under **Actions** and filters expand explicitly; a count keeps active filters visible when collapsed. Compact summaries leave the first roll identity visible above the bottom navigation on the tested 390 × 844 viewport.

The summary describes all active inventory; the result count describes the loaded, filtered rows. These are deliberately different scopes. Existing server-side filtering and cursor pagination remain. Search, material, state, archive mode, exact product and low-stock filters are reflected in the URL, including reload and Back/Forward. Search changes replace the current history entry; explicit filter changes create a reversible entry. Inputs are bounded to the existing API limits. Warning filtering runs on the server before pagination and uses each product's inclusive threshold; zero-weight rolls are handled by the Empty filter. The summary buttons open the corresponding **global active inventory** view and deliberately clear unrelated filters.

A same-filter refresh keeps the current card nodes and focus while loading, then refreshes the loaded window rather than collapsing it to the first page. Failed refreshes leave the matching rows visible with an error. Filter changes clear unrelated rows immediately and invalidate old responses. Dragging suspends background refreshes (including already outstanding replies); refreshing resumes when the drag ends. Product cards show recorded physical properties and aggregate active stock, with no invented temperatures or weights. **View spools** uses an exact product ID, not a text approximation. Clearing this filter also removes it from the URL. Product-gallery summaries use only the matching products for product count, active roll count and material weight. The complete product collection can be sorted by natural brand/product/color name, material, least stock or most stock, with stable ties and locale-aware natural ordering. The gallery sort is a saved browser preference; gallery search filters remain local to its mounted view. This is not a page-local sort of a partially loaded spool inventory.

## Drag-and-drop and non-drag alternatives

| Action | Drop behavior | Click / keyboard alternative | Server write |
| --- | --- | --- | --- |
| Spool into label tray | Adds a unique roll to the current print selection | Selection checkbox or selection handle button | None |
| Reorder selected labels | Moves the roll to the selected target position | Move up / Move down buttons | None |
| Inventory CSV | Selects the file and prepares the existing validation preview | Choose file | Import requires its existing explicit confirmation |
| Spoolman JSON | Selects the local snapshot | Choose file | Preview and import remain explicit |
| G-code / 3MF metadata | Selects a file for inspection | Choose file | Inspection/application steps remain explicit; no printer transfer |
| STL | Selects the model | Choose file | Slicing remains explicit; no automatic print start |
| Spool onto a printer | Stages printer and spool in the slot form | Select a spool, then choose a target, or use the existing dropdowns | Only **Save slot assignment** updates the logical mapping |

Native desktop HTML drag-and-drop is a convenience, not a requirement. Touch and keyboard users have visible controls for every action. A drag never starts, stops or resumes a physical print and never deducts stock. Slot mappings are records only, not physical filament changes.

File drop zones reject multiple files, empty files, disallowed extensions and oversized files before emitting a selection. Invalid replacement files invalidate old previews. The extension check is only an early UX check: existing server parsing, limits, authorization and validation remain authoritative. CSV/JSON limits are 2 MiB, metadata 16 MiB and STL 8 MiB. Dropping a file elsewhere does not navigate away from an open draft.

## Label selection lifecycle

The tray holds up to 100 unique spool UUIDs and preserves the explicit order in the print URL. Selection survives filtering, pagination, switching views and inventory refreshes while the spool page remains mounted. Selected items outside the current filter remain visible in the tray; visible snapshots are refreshed when fresh data is available. The server reads current spool data when generating the label sheet.

Selection is intentionally not persisted across page reloads or navigation away from the spool page. **Select loaded labels** adds the currently loaded results in their displayed order; it is not a hidden select-all across unloaded pages. **Deselect loaded labels** keeps selections outside the active filters. Batch selection is all-or-nothing at the same 100-label cap. Dragging a selected label displays its insertion side, and moving it announces the resulting position. **Clear selection** is explicit. Selecting or sorting labels changes no physical stock. The currently selected interface language is carried to the label page.

## Regression checks

Run the normal frontend tests, `npm run i18n:check`, typecheck, production build, API contract check and backend suite. New unit tests cover appearance lifecycle, blocked storage, file picker/drop validation, ordered and bounded selection, stale/foreign drags and editor/viewer slot preparation. Backend regressions exercise exact product filtering with pagination/archive combinations and preservation of label order.

`scripts/browser_smoke.py` retains the existing English/German workflows and also runs `scripts/ui_browser_smoke.py`: native mouse dragging, click fallbacks, file-drop previews, separate slot confirmation, product filters, draft preservation, theme persistence/system updates, mobile drawer interactions and page overflow checks at 320, 390, 768, 1024, 1440 and 1920 px. CI publishes genuine light/dark/mobile screenshots as `ui-ux-previews`. Screenshot data is synthetic and exists only in the ephemeral browser-test database. These checks do not constitute a hardware certification or a complete accessibility audit.

The follow-up regressions in `scripts/ui_followup_smoke.py` cover URL reload/history, combined low-stock filters, bounded bulk label selection, reorder feedback, and unchanged card DOM during a delayed refresh. These flows assert the inventory snapshot remains unchanged.

The concurrent gallery and file-drop feedback improvements remain covered by `catalog_browser_smoke.py`, the product-view/component suites and file-drop feedback regressions.

## Mobile legibility and warehouse board navigation (Issue #10)

The mobile layout uses at least 11px for compact inventory metric labels, 12px for secondary spool labels and 16px for mobile text and select inputs to mitigate mobile-browser focus zoom. Drag handles, label-tray arrows and card actions provide at least 44px targets on narrow screens and devices reporting coarse pointer input. The stored filament properties and stock operations are unaffected.

The horizontal **Locations** board exposes explicit **Previous/Next** buttons, operable by keyboard and touch. Each button is disabled at the corresponding actual scroll boundary; controls recalculate on resizing and when loaded location lanes change. Direct touch swiping and horizontal keyboard scrolling within the focusable board remain available. Scrolling never stages or saves a location change. The original physical verification and explicit save gate remain mandatory.

The Angular unit suite validates scroll limits and absence of inventory writes. Real Chromium smoke checks exercise keyboard board scrolling, computed mobile font/control sizes, existing drag/drop confirmations, and the first spool visibility above the fixed bottom navigation at 390 × 844. This is **not** physical iOS Safari, iPhone, screen-reader or 3D-printer certification; real-device acceptance remains a separate validation scope.
