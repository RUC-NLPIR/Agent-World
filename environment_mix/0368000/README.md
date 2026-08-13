# LedgerPulse Ops Hub

LedgerPulse Ops Hub is a small finance-ops automation service that models QuickBooks receivables, basic expense/account data, Google Sheets logs, and Gmail communications in one store for tool-driven workflows.

## Datastore

### `world.json` — object of 3 records keyed by identifier
Holds per-connector snapshots (Gmail, QuickBooks, and Google Sheets) so the service can drive automations using a single consolidated view of messages, invoices, accounts, expenses, and spreadsheets.
Keys look like: gmail, quickbooks, google_sheets

- `account` — string
- `messages` — array
  each record in `messages` has:
  - `id` — string
  - `from_` — string
  - `to` — array
  - `cc` — array
  - `bcc` — array
  - `subject` — string
  - `body_plain` — string
  - `body_html` — null — nullable
  - `label_ids` — array
  - `is_read` — boolean
  - `is_starred` — boolean
  - `date` — integer
  - `internal_date` — integer
- `invoices` — array
  each record in `invoices` has:
  - `id` — string
  - `customer` — string
  - `amount` — number
  - `balance` — number
  - `status` — string — one of open, overdue, paid
  - `due_date` — string
  - `issue_date` — string
- `expenses` — array
  each record in `expenses` has:
  - `id` — string
  - `vendor` — string
  - `amount` — number
  - `category` — string
  - `date` — string
- `accounts` — array
  each record in `accounts` has:
  - `id` — string — one of ACC-CC, ACC-CHK, ACC-SAV
  - `name` — string — one of Checking, Corporate Card, Savings
  - `balance` — number
  - `type` — string — one of bank, credit_card
- `spreadsheets` — array
  each record in `spreadsheets` has:
  - `id` — string — one of fin-1, fin-2
  - `name` — string — one of AR_Aging, Expense_Log
  - `worksheets` — array
    each record in `worksheets` has:
    - `title` — string — one of Expenses, Sheet1
    - `values` — array
