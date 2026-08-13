# Keystone Task Console

Keystone Task Console is a simple task-tracking service that lets users create tasks, list users, and update task status.

## Datastore

### `mock_db.json` — object of 2 records keyed by identifier
Keys look like: tasks, users

- `task_1` — object
  each record in `task_1` has:
  - `task_id` — string
  - `title` — string
  - `description` — string
  - `status` — string
- `user_1` — object
  each record in `user_1` has:
  - `user_id` — string
  - `name` — string
  - `tasks` — array
