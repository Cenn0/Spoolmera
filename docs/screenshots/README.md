# UI screenshots — source and regeneration

[← Documentation index](../README.md) · [← Project README](../../README.md)

The screenshots committed here are **real headless-Chromium captures of the compiled Angular application**. They show a **disposable synthetic test inventory** in German, not production data or a connected physical 3D printer. They are not AI-generated mockups, stock imagery or manually composed UI previews.

| Committed image | Actual browser view |
| --- | --- |
| [`filaments-dark.png`](filaments-dark.png) | Material/filament gallery, dark mode |
| [`spools-dark.png`](spools-dark.png) | Physical spool cards, dark mode |
| [`spools-light.png`](spools-light.png) | Physical spool cards, light mode |
| [`locations-dark.png`](locations-dark.png) | Physical spool location board, dark mode |
| [`spools-mobile-dark.png`](spools-mobile-dark.png) | Mobile spool view, dark mode |

## Verified origin

- **Application revision:** [`ed706cc020df2f4871113d86271c7d9f0cc026ea`](https://github.com/Cenn0/Spoolmera/commit/ed706cc020df2f4871113d86271c7d9f0cc026ea) (Spoolmera v0.10.0).
- **CI run:** [`38047886348`](https://github.com/Cenn0/Spoolmera/actions/runs/38047886348), completed successfully on **2026-10-10**.
- **Artifact:** `ui-ux-previews`, five original `ui-de-*.png` files.
- **Test code:** [`scripts/ui_browser_smoke.py`](../../scripts/ui_browser_smoke.py), called from [`scripts/browser_smoke.py`](../../scripts/browser_smoke.py) in the [`browser-smoke` CI job](../../.github/workflows/ci.yml).
- **Image handling:** original PNG binaries copied unmodified to stable filenames; no cropping, pixel alteration or compositing.

The files are committed to the repository so they remain visible after GitHub Actions artifacts expire. Browser fixtures do not prove physical printer compatibility or constitute a comprehensive accessibility audit.

## Refresh procedure

1. Run the complete `browser-smoke` job on the intended code revision with a **fresh disposable test database**. Confirm the run is successful.
2. Download its `ui-ux-previews` artifact from Actions. Check that the required `ui-de-*.png` images are present.
3. Replace the five files here, mapping `ui-de-dark-filaments` → `filaments-dark`, `ui-de-dark-locations` → `locations-dark`, `ui-de-dark-spools` → `spools-dark`, `ui-de-light-spools` → `spools-light`, and `ui-de-mobile-dark` → `spools-mobile-dark`.
4. Open all images at full size: verify layout, readable typography, language, error-free UI, suitable fixtures and absence of secrets or personal data.
5. Update the revision, CI run, date and descriptions on this page. Commit the actual PNGs together with README references. Do not use an expiring Actions artifact URL as the README image source.

Do not photograph live user inventory for public documentation. If functionality changed, update the docs and test the behavior separately; screenshots are only visual evidence.
