# ForgeSight Quality Hub

ForgeSight Quality Hub is a Notion-backed quality control workspace for tracking inspections, supplier oversight, and corrective actions.

## Datastore

### `notion_pages.json` — object of 10 records keyed by identifier
Stores Notion pages (titles and content blocks) used as narrative workspace hubs and recurring reports so the service can publish and organize QC notes and checklists.
Keys look like: page_home, page_weekly, page_weekly_w13

- `id` — string
- `title` — string
- `blocks` — array
  each record in `blocks` has:
  - `type` — string — one of bulleted_list, heading_1, heading_2, paragraph, to_do
  - `text` — string
  - `checked` — boolean
- `parent` — object
  each record in `parent` has:
  - `type` — string — one of database_id, page_id, workspace
  - `page_id` — string
  - `database_id` — string

### `notion_databases.json` — object of 4 records keyed by identifier
Stores Notion databases and their rows for structured QC operational records (e.g., defects, suppliers, CAPA, inventory) so the service can track and query tabular quality data.
Keys look like: Defects, Suppliers, CAPA

- `id` — string
- `schema` — object
  each record in `schema` has:
  - `Lot` — string
  - `DefectRate` — string
  - `Status` — string
  - `Supplier` — string
  - `Inspector` — string
  - `Date` — string
  - `RootCause` — string
  - `Name` — string
  - `Tier` — string
  - `Score` — string
  - `Contact` — string
  - `Email` — string
  - `LastAudit` — string
  - `ID` — string
  - `Source` — string
  - `Owner` — string
  - `Opened` — string
  - `Due` — string
  - `Summary` — string
  - `SKU` — string
  - `Description` — string
  - `Qty` — string
  - `ReorderPt` — string
  - `Location` — string
- `rows` — array
  each record in `rows` has:
  - `id` — string
  - `Lot` — string
  - `DefectRate` — number
  - `Status` — string — one of active, closed, escalated, in-progress, ok, onboarding, open, review
  - `Supplier` — string — one of Apex, BoxCo, Harbor, Internal, PartsCo
  - `Inspector` — string
  - `Date` — string
  - `RootCause` — string
  - `Name` — string — one of Apex Fasteners, BoxCo, GasketPro, Harbor Metals, PartsCo
  - `Tier` — string — one of 1, 2
  - `Score` — integer
  - `Contact` — string — one of Dana Park, Elena Voss, Mira Tan, Ravi Menon, Sam Cole
  - `Email` — string
  - `LastAudit` — string — one of , 2023-08-22, 2023-09-12, 2023-10-04, 2023-11-15
  - `ID` — string — one of CAPA-2024-014, CAPA-2024-015, CAPA-2024-016, CAPA-2024-017, CAPA-2024-018, CAPA-2024-019, CAPA-2024-020
  - `Source` — string — one of audit, calibration, lot-240302, lot-240305, lot-240309, lot-240317, supplier
  - `Owner` — string
  - `Opened` — string — one of 2024-03-20, 2024-03-22, 2024-03-23, 2024-03-24, 2024-03-27, 2024-03-28, 2024-03-29
  - `Due` — string — one of 2024-03-27, 2024-03-28, 2024-04-05, 2024-04-10, 2024-04-15, 2024-04-20, 2024-05-01
  - `Summary` — string
  - `SKU` — string
  - `Description` — string
  - `Qty` — integer
  - `ReorderPt` — integer
  - `Location` — string — one of Cal Lab, MRO R2, Tool Room, WH-A R3, WH-A R4, WH-B R1, WH-C R1
