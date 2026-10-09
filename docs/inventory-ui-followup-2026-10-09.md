# Spool interaction follow-up — 2026-10-09

## Reviewed baseline

Commit `774612679675358090b8da5cf4add238cab77b3b`, tree `dd82dd9797128ae3a3228be885ac99e1ec5dd82e`, open PR #8. CI run #113 had all five gates passing. Its actual light/dark and mobile Chromium screenshots were inspected. A hash-verified source snapshot reproduced 244 backend and 87 Angular passing tests locally.

The baseline already implements a live EN/DE interface, light/dark/system preferences, color-card inventories, an ordered label tray, validated file drops and explicit logical printer slot preparation. Those features were retained rather than replaced or claimed as new work.

## Concurrent work preserved

Before publication, PR #8 advanced to `3cc507fdfa7e28c8784c72c5712c7a44251a1fd2`. Its product gallery, natural/multi-term search, local sort preference, matching summaries, contextual edit labels, empty states, file-size guidance and all tests are retained unchanged. This follow-up adds the complementary spool/navigation/selection fixes. See `ui-review-followup-2026-10-09.md` for that catalogue review.

## Confirmed issues and completed changes

| Finding | Change | Regression evidence |
| --- | --- | --- |
| Only some spool filters were read from or written to navigation; reload/back could reset material or state. | All supported filters have explicit URL state, bounded input and clear behavior. | Reactive route unit tests and browser reload/Back/Forward. |
| Every spool refresh cleared the result array and reduced loaded pages. | Keep mounted nodes during refresh, refresh the loaded window, retain rows on failure and reject stale responses; suspend refresh during drags. | Deferred responses, DOM identity/focus tests, pagination and real browser delayed response. |
| Low-stock statistics were not an actionable inventory filter. | Global read-only shortcuts plus an optional server-side low-stock condition, before cursor pagination. | Inclusive/zero thresholds, archive/status/material/product/search combinations, no stock/movement changes. |
| Repeated label selection was cumbersome; reorder destination/feedback was weak. | Bounded bulk select/deselect for loaded rows, preserved outside-filter selection, insertion indicators and localized position announcements. | Unit, native drag and click-alternative browser tests. |
| Mobile summary labels could split German compound words arbitrarily. | Compact two-column metrics and less desktop drag-help text above the phone inventory. | Existing six-width browser sweep and mobile screenshot; no universal accessibility claim. |

## Boundaries

No new runtime dependency, external UI asset, schema migration, automatic stock adjustment or physical printer operation is introduced. The low-stock parameter is additive and retains the existing cursor and default API behavior. Filament product sorting uses the full product collection; physical spools remain ID-paginated. Native dragging still has click and keyboard alternatives. Theme and language remain browser preferences. Labels stay limited to 100 and selection still clears on navigation away or page reload.

The system Chromium on the editing host refuses local application navigation with `ERR_BLOCKED_BY_ADMINISTRATOR`; its policy was not changed. Actual browser verification and screenshots therefore use the project's GitHub Actions Chromium gate. Backend, Angular unit tests, contracts, translation checks and builds run locally as well. Docker and physical hardware are not available on the editing host.
