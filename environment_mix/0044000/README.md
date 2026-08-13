# LedgerLeaf SheetOps Hub

LedgerLeaf SheetOps Hub is a service that stores and operates on a small set of named Google Sheets used for tracking operational data and reporting.

## Datastore

### `spreadsheets.json` — object of 7 records keyed by identifier
Holds the catalog of known spreadsheets and their worksheet contents so the service can read, update, and append tabular data by spreadsheet/worksheet name.
Keys look like: Defect_Tracker, Q1_Content_Budget, Supplier_Scorecard

- `id` — string — one of sheet_capa, sheet_dt, sheet_fc, sheet_inv, sheet_ps, sheet_q1cb, sheet_ss
- `worksheets` — object
  each record in `worksheets` has:
  - `Lots` — array
  - `Summary` — array
  - `BySupplier` — array
  - `Budget` — array
  - `Campaigns` — array
  - `March2024` — array
  - `YTD` — array
  - `Stock` — array
  - `Reorders` — array
  - `W13` — array
  - `Capacity` — array
  - `Open` — array
  - `Closed` — array
  - `Q1` — array
