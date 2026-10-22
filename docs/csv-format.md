# Inventory CSV format — schema v1

This is a **snapshot format for product and active-spool inventory**, not a history-preserving database backup. It is intentionally strict to avoid silent corruption.

## Export and import endpoints

- \`GET /api/export/inventory.csv\`: download a UTF-8 CSV file, including a BOM for compatibility with common spreadsheet programs.
- \`POST /api/import/inventory.csv?dry_run=true\`: preview a CSV import, with request header \`Content-Type: text/csv\`. The default is dry-run.
- \`POST /api/import/inventory.csv?dry_run=false\`: apply a validated import transaction.

The inventory endpoints require authentication. Export is available to authenticated users including viewers; importing requires editor or administrator rights and valid session/CSRF protection. The user interface handles import preview and confirmation.

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

## Movement-history export — separate schema v1

The **History** page offers **Export full history CSV** for all records matching the
**last applied** filters, including not-yet-loaded pages and archived spools. This
is a read-only audit/reporting export, not an inventory import format and not a
full database backup.

Authenticated endpoint: `GET /api/movements/export.csv`

Supported query parameters match `GET /api/movements/page`:

| Parameter | Behavior |
| --- | --- |
| `q` | Accent/case-insensitive multi-term search over history fields; `%` and `_` are literal; maximum 120 characters |
| `kind` | `initial`, `consume` or `adjust` |
| `spool_id`, `job_id`, `actor_id` | Positive integer identifiers |
| `source` | Exact movement source identifier, maximum 80 characters |
| `from_date`, `to_date` | Inclusive UTC calendar dates (`YYYY-MM-DD`); reversed dates return 422 |

No pagination cursor or `limit` is needed: the endpoint streams **every matching
row**, ordered by descending movement ID. An empty result still yields the
header row. The export uses one SQLite read snapshot and fetches small batches;
it does not modify ledger entries. Movements created after the snapshot are excluded.

The download uses UTF-8 with BOM, comma delimiters, RFC-style CSV quoting and CRLF
row endings. It is sent with `Cache-Control: no-store` and the fixed attachment
filename `spoolmera-movements-v1.csv`.

**Exact columns for movement-history CSV schema v1:**

```csv
schema_version,movement_id,created_at,spool_id,spool_uid,brand,product_name,material,color_name,kind,delta_g,remaining_after_g,source,source_ref,actor_id,actor_name,job_id,job_file_name,corrects_movement_id,accounting_operation_id,note
```

`schema_version` is `1`. Stock changes and balances are integer grams. IDs,
references, user/job data and notes make reconciliations traceable. Missing
optional values become empty cells; records are never silently truncated to
the UI's 50-row page. Spreadsheet-formula-looking text receives an apostrophe
prefix; numeric negative gram values remain numeric.

Downloaded history and usernames may be sensitive: limit user access and
protect exported files. For full-fidelity recovery use SQLite backup/restore,
not CSV. **There is no history CSV importer** because replaying historical
movements could violate balance and idempotency invariants.
