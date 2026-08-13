# Todoist Task and Project Manager

This service provides an MCP-compatible interface for managing Todoist productivity items such as tasks and projects.

## Datastore

### `dataset.json` — single document
Holds the service’s stored records and related metadata so the Todoist Task and Project Manager can track and expose items through its tools.

- `server` — string
- `description` — string
- `records` — array
  each record in `records` has:
  - `id` — string — one of todoist__1001, todoist__1002, todoist__1003, todoist__1004, todoist__1005, todoist__1006
  - `name` — string — one of Alice Johnson, Bob Smith, Carol Lee, David Kim, Eva Martinez, Frank Brown
  - `title` — string
  - `status` — string — one of active, archived, completed, draft, pending
  - `created_at` — string
- `_meta` — object
  each record in `_meta` has:
  - `primary_collection` — string
  - `record_count` — integer
  - `fields` — array
