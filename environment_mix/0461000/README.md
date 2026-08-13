# HelioOps Marketing Automations

HelioOps Marketing Automations is a small automation service that surfaces and simulates interactions across Slack, Mailchimp, and Google Sheets for marketing operations.

## Datastore

### `world.json` — object of 3 records keyed by identifier
Stores the per-integration snapshots (Slack, Mailchimp, and Google Sheets) that the service uses to list, read, and simulate actions against those external systems.
Keys look like: slack, mailchimp, google_sheets

- `bot_user_id` — string
- `channels` — array
  each record in `channels` has:
  - `id` — string — one of C_ANALYTICS, C_CONTENT, C_MKT
  - `name` — string — one of analytics, content, marketing
  - `is_private` — boolean
- `messages` — array
  each record in `messages` has:
  - `id` — null — nullable
  - `ts` — string
  - `channel_id` — string — one of C_ANALYTICS, C_CONTENT, C_MKT
  - `user_id` — string — one of U_BOT, U_MGR, U_MK1, U_MK2, U_MK3
  - `text` — string
  - `thread_ts` — null — nullable
  - `reply_count` — integer
  - `is_bot` — boolean
  - `reactions` — array
    each record in `reactions` has:
    - `name` — string
    - `user_ids` — array
    - `count` — integer
- `audiences` — array
  each record in `audiences` has:
  - `id` — string — one of aud-1, aud-2, aud-3, aud-4
  - `name` — string — one of Enterprise Prospects, Newsletter, Product Updates, Webinar Attendees
  - `member_count` — integer
- `campaigns` — array
  each record in `campaigns` has:
  - `id` — string
  - `title` — string
  - `audience_id` — string — one of aud-1, aud-2, aud-3, aud-4
  - `status` — string — one of draft, scheduled, sent
  - `emails_sent` — integer
  - `opens` — integer
  - `clicks` — integer
  - `send_time` — string — nullable
- `spreadsheets` — array
  each record in `spreadsheets` has:
  - `id` — string — one of sheet-1, sheet-2
  - `name` — string — one of Audience_Roster, Q1_Content_Budget
  - `worksheets` — array
    each record in `worksheets` has:
    - `title` — string — one of Roster, Sheet1
    - `values` — array
