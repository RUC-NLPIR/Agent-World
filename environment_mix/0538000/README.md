# Pinnacle Expense Ledger

Pinnacle Expense Ledger is a finance service for submitting and tracking employee expense reports.

## Datastore

### `expense_reports.json` — list of 40 records
Stores expense report submissions with totals and line-item counts so the service can track each report through its review workflow.
Lifecycle field `status`, states observed: approved, pending, rejected, submitted

- `report_id` — string
- `employee` — string
- `status` — string — one of approved, pending, rejected, submitted
- `total` — number
- `items` — integer
