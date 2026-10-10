# English and German interface

The web interface supports `en` and `de` in the same application build. Choose **English** or **Deutsch** on the sign-in page or in the application header. Switching updates existing views without navigation, another login or a database migration. Unsaved form fields, reviewed import previews and consumption decisions remain in place.

## Preference and formatting

On startup the UI uses a valid saved browser choice, then the language cookie, then the first supported language in the browser's ordered preferences. Regional German preferences such as `de-AT` and `de-CH` select German; English variants select English. Unsupported preferences fall back to English.

An explicit choice is stored under `spoolmera.language` in local storage and in the non-secret `fm_language` cookie. The cookie is limited to `en` or `de`, uses `SameSite=Lax`, and is marked `Secure` on HTTPS. Blocked storage does not prevent the application from opening or the current page from changing language. The preference belongs to the browser, not an account. Other open tabs respond to changes through the browser's storage event. The document language and title update for assistive technology and browser tools.

Weights, decimal numbers, prices and date-time values use `en-US` or `de-DE` formatting. The stored currency is retained; selecting German does not convert an amount to euros. Calendar-only purchase dates retain the existing ISO presentation in English and use `DD.MM.YYYY` in German. Date-time displays retain the browser's local time zone. Native date and number controls still submit the same machine values to the API.

Product, brand, color, user, printer and file names, notes, locations and batch identifiers are user data and are displayed as entered. API enum values, identifiers, CSV formats, external catalog records and hardware protocols are unchanged. Known application errors have German translations, including validation details and stale measurement/conflict instructions. Unknown external controller diagnostics remain available in their original wording.

## Printable labels

Both individual and batch label pages support `?lang=en` and `?lang=de`. Their preference order is explicit query, valid `fm_language` cookie, supported `Accept-Language` preferences, then English. Label format links preserve the chosen language. HTML `lang`, `Content-Language`, caching and the original HTML escaping are covered by tests. QR targets and spool identities do not depend on language. Both 60 × 40 mm and 50 × 30 mm formats remain available.

## Translation maintenance

Translation catalogs live under `frontend/src/app/core/i18n/`. English source text is the lookup key; its German counterpart is stored in the relevant feature catalog. The application includes these local files and needs no translation service or additional runtime dependency.

For static text, use `{{'English source' | t}}`. Bind placeholders, titles and accessible labels through the same pipe. Conditions and enum display labels must also pass through translation; their request values must stay unchanged. Avoid translating interpolated user data as if it were an application message.

Use named parameters for full sentences so German can use a different word order:

```html
{{'Spool #{id}' | t:{id: '' + spool.id} }}
```

Numbers supplied as parameters are formatted for the selected language. Pass technical identifiers as strings when digit grouping would be inappropriate. Use `i18n.grams`, `i18n.money`, `i18n.number`, `i18n.dateText` and `i18n.dateOnly` for displayed values.

For a notice or error that must remain visible across language changes, store `i18n.message(source, params)` and render it through `t`. Parameters may themselves be localized messages, preserving nested backend-error context. Immediate browser confirmation dialogs use `i18n.t(source, params)`. Translation interpolation is ordinary Angular text binding; do not replace it with `innerHTML`.

Run `npm run i18n:check`, `npm test`, `npm run typecheck` and `npm run build` from `frontend/`. The static check parses component templates and translation references, detects missing German keys and flags untranslated application prose. Shared entries must agree and preserve all named parameters. Unit regressions verify language negotiation, blocked storage, live forms, saved notices, conflict state, formatting and escaped interpolation.

## Browser verification

The existing English browser workflow remains intact. A second `de-DE` browser context verifies automatic language choice, English/German switching while credentials and job drafts are entered, translated login errors, every navigation destination, saved preference after reload, German number formatting, unchanged user data, localized label pages and the mobile layout. Successful runs retain German desktop/mobile screenshots in the `german-interface-previews` CI artifact; failures retain browser traces and screenshots.

Use the commit-specific CI result before installing a test artifact. The unit or static checks alone are not evidence that the real browser gate passed.

For appearance, inventory cards, drag-and-drop alternatives and mobile navigation, see [Interface UX](interface-ux.md).
