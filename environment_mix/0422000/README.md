# Keystone Support Desk

Keystone Support Desk is a ticketing service for tracking support issues and the discussion around them.

## Datastore

### `tickets.json` — list of 120 records
Holds the core ticket records (who reported what, when, and how it is being handled) so the service can list, filter, search, and summarize work items.
Lifecycle field `status`, states observed: open, pending, solved

- `ticket_id` — string
- `subject` — string
- `status` — string — one of open, pending, solved
- `priority` — string — one of high, low, normal, urgent
- `requester` — string
- `assignee` — string
- `created` — string
- `tags` — array

### `comments.json` — list of 248 records
Holds per-ticket comment entries so the service can show and add conversation history associated with tickets.

- `comment_id` — string
- `ticket_id` — string
- `author` — string
- `body` — string
- `at` — string
