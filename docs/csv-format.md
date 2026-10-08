# Inventory CSV format — schema v1

This is a **snapshot format for product and active-spool inventory**, not a history-preserving database backup. It is intentionally strict to avoid silent corruption.

## Export and import endpoints

- \`GET /api/export/inventory.csv\`: download a UTF-8 CSV file, including a BOM for compatibility with common spreadsheet programs.
- \`POST /api/import/inventory.csv?dry_run=true\`: preview a CSV import, with request header \`Content-Type: text/csv\`. The default is dry-run.
- \`POST /api/import/inventory.csv?dry_run=false\`: apply a validated import transaction.

The user interface handles preview and confirmation. Both endpoints are intended for trusted, local use; there is currently no authentication.

## Columns

The header must contain these **15 exact column names** (order may vary):

\`\`\`csv
schema_version,product_uid,brand,name,material,color_name,color_hex,diameter_mm,product_notes,spool_uid,initial_g,remaining_g,opened,location,spool_notes
\`\`\`

| Field | Meaning |
| --- | --- |
| \`schema_version\` | Literal \`1\` |
| \`product_uid\` | Canonical UUID (stable product ID) |
| \`brand\`, \`name\` | Required product text |
| \`material\` | Required material type (e.g. PLA, PETG); normalized to uppercase |
| \`color_name\` | Required readable color name |
| \`color_hex\` | Hex color in \`#RRGGBB\` form |
| \`diameter_mm\` | Filament diameter, decimal with dot |
| \`product_notes\` | Optional text |
| \`spool_uid\` | Canonical UUID for the physical spool, or blank for a product-only row |
| \`initial_g\` | Whole grams, between 1 and 100,000 |
| \`remaining_g\` | Whole grams, between 0 and \`initial_g\` |
| \`opened\` | Exact \`true\` or \`false\` for spool rows |
| \`location\`, \`spool_notes\` | Optional text |

For products without active spools, export emits a row with an empty \`spool_uid\` and empty spool-specific columns. Multiple spools of the same product repeat the product columns and UUID. These repetitions must have consistent values.

Imports are all-or-nothing: maximum **2 MiB**, **2,500 data rows**, UTF-8 with optional BOM, RFC-style comma-separated quoting, no embedded NUL bytes. Invalid data causes HTTP 422 or 413 with no partial inserts.

## Data retention and conflict rules

- All products and *non-archived* spools are exported. The movement ledger and archived spool details are excluded.
- Existing product UUIDs and spool UUIDs are **never overwritten**. In particular, importing an old CSV must not reset newer consumption, unarchive spools, or change locally edited product details.
- New products and spools are created with the supplied stable UUIDs.
- Imported spools receive an \`initial\` ledger event for their **remaining** weight and a note indicating CSV import. Earlier movement history is not reconstructed.
- Duplicate spool UUIDs inside one CSV are rejected; a spool UUID already associated with another product UUID is rejected.
- The preview reports would-be creates/skips but is not a guaranteed reservation; concurrent changes may alter the apply result.

## Spreadsheet safety

Exports prefix strings that could be evaluated as spreadsheet formulas with an apostrophe; the importer reverses its own protection. Do not manually remove safety prefixes before viewing edited files in spreadsheet software. CSV is a data interchange format, **not** a security boundary against arbitrary spreadsheets.

For full-fidelity backups, use SQLite's backup mechanism or a consistent snapshot, not CSV.
