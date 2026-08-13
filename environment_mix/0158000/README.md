# Crescent HR Orchestration Hub

Crescent HR Orchestration Hub is a small automation workspace that centralizes BambooHR employee and time-off data alongside Gmail and Slack messages for HR-style workflows and notifications.

## Datastore

### `world.json` — object of 3 records keyed by identifier
Holds the per-system snapshots for gmail, slack, and bamboohr so the service can read and write across these tools in one place.
Keys look like: gmail, slack, bamboohr

- `account` — string
- `messages` — array
  each record in `messages` has:
  - `id` — string — nullable
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
  - `ts` — string
  - `channel_id` — string — one of C_GEN, C_HIRING, C_HR
  - `user_id` — string — one of U_BOT, U_HR1, U_HR2, U_REC
  - `text` — string
  - `thread_ts` — null — nullable
  - `reply_count` — integer
  - `is_bot` — boolean
  - `reactions` — array
- `bot_user_id` — string
- `channels` — array
  each record in `channels` has:
  - `id` — string — one of C_GEN, C_HIRING, C_HR
  - `name` — string — one of general, hiring, people-ops
  - `is_private` — boolean
- `employees` — array
  each record in `employees` has:
  - `id` — string
  - `first_name` — string
  - `last_name` — string
  - `department` — string
  - `job_title` — string
  - `status` — string — one of active, on_leave, terminated
  - `hire_date` — string
  - `manager_id` — string — nullable
  - `pto_balance_days` — integer
  - `work_email` — string
- `time_off_requests` — array
  each record in `time_off_requests` has:
  - `id` — string
  - `employee_id` — string
  - `start` — string
  - `end` — string
  - `type` — string — one of bereavement, personal, sick, unpaid, vacation
  - `status` — string — one of approved, denied, pending
