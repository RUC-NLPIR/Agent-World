# Helio Support Automation Hub

Helio Support Automation Hub is a service for exercising simple support-workflow automations across Zendesk tickets, Gmail messages, and Slack channels/messages.

## Datastore

### `world.json` — object of 3 records keyed by identifier
Holds per-system snapshots (gmail, slack, zendesk) of accounts, communications, and support artifacts so the service can drive and observe automation scenarios across these tools.
Keys look like: gmail, slack, zendesk

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
  - `channel_id` — string — one of C_GEN, C_INCIDENTS, C_SUPPORT, C_T2
  - `user_id` — string — one of U_AG1, U_AG2, U_AG3, U_BOT, U_LEAD
  - `text` — string
  - `thread_ts` — null — nullable
  - `reply_count` — integer
  - `is_bot` — boolean
  - `reactions` — array
    each record in `reactions` has:
    - `name` — string
    - `user_ids` — array
    - `count` — integer
- `bot_user_id` — string
- `channels` — array
  each record in `channels` has:
  - `id` — string — one of C_GEN, C_INCIDENTS, C_SUPPORT, C_T2
  - `name` — string — one of general, incidents, support, tier-2
  - `is_private` — boolean
- `tickets` — array
  each record in `tickets` has:
  - `id` — string
  - `subject` — string
  - `status` — string — one of closed, open, pending, solved
  - `priority` — string — one of high, low, normal, urgent
  - `requester_email` — string
  - `assignee_email` — string — nullable
  - `tags` — array
  - `created_at` — string
  - `satisfaction` — string — one of bad, good, unoffered
- `comments` — array
  each record in `comments` has:
  - `id` — string
  - `ticket_id` — string
  - `author_email` — string
  - `public` — boolean
  - `body` — string
  - `created_at` — string
