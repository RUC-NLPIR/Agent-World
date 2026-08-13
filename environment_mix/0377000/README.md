# OpsSync Automation Hub

OpsSync Automation Hub is a small integration service that centralizes operational data surfaced from Slack, Asana, and Google Sheets for automation and testing workflows.

## Datastore

### `world.json` — object of 3 records keyed by identifier
Holds the persisted snapshot of third-party workspace state (Slack, Asana, and Google Sheets) so the service can drive and observe automation scenarios against a single backing store.
Keys look like: slack, asana, google_sheets

- `bot_user_id` — string
- `channels` — array
  each record in `channels` has:
  - `id` — string — one of C_GEN, C_INC, C_OPS, C_VENDOR
  - `name` — string — one of general, incidents, ops, vendors
  - `is_private` — boolean
- `messages` — array
  each record in `messages` has:
  - `id` — null — nullable
  - `ts` — string
  - `channel_id` — string — one of C_GEN, C_INC, C_OPS, C_VENDOR
  - `user_id` — string — one of U_BOT, U_LEAD, U_OPS1, U_OPS2, U_OPS3
  - `text` — string
  - `thread_ts` — null — nullable
  - `reply_count` — integer
  - `is_bot` — boolean
  - `reactions` — array
    each record in `reactions` has:
    - `name` — string
    - `user_ids` — array
    - `count` — integer
- `projects` — array
  each record in `projects` has:
  - `id` — string — one of P-1, P-2, P-3, P-4, P-5, P-6
  - `name` — string
  - `status` — string — one of active, on_hold
- `tasks` — array
  each record in `tasks` has:
  - `id` — string
  - `name` — string
  - `project_id` — string — one of P-1, P-2, P-3, P-4, P-5, P-6
  - `assignee` — string
  - `due_on` — string
  - `completed` — boolean
  - `priority` — string — one of high, low, normal, urgent
- `spreadsheets` — array
  each record in `spreadsheets` has:
  - `id` — string — one of ops-1, ops-2
  - `name` — string — one of Project_Status, Vendor_Tracker
  - `worksheets` — array
    each record in `worksheets` has:
    - `title` — string — one of Sheet1, Status
    - `values` — array
