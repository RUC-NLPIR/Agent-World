# Helio Workspace Messenger

Helio Workspace Messenger is a workspace messaging service for managing users, contacts, and message interactions.

## Datastore

### `state.json` — single document
Holds the service-wide workspace state used to track user identity mappings, the current user, inbox-related identifiers, and counters that support messaging operations.

- `generated_ids` — array
- `user_count` — integer
- `user_map` — object
  each record in `user_map` has:
  - `Alice` — string
  - `Bob` — string
  - `Catherine` — string
  - `Daniel` — string
  - `Eve` — string
  - `Frank` — string
  - `Grace` — string
  - `Henry` — string
  - `Iris` — string
  - `Jack` — string
  - `Karen` — string
  - `Liam` — string
- `inbox` — array
  each record in `inbox` has:
  - `USR002` — string
  - `USR003` — string
  - `USR004` — string
  - `USR005` — string
  - `USR006` — string
  - `USR001` — string
  - `USR007` — string
  - `USR008` — string
  - `USR009` — string
  - `USR010` — string
  - `USR011` — string
  - `USR012` — string
- `message_count` — integer
- `current_user` — string
- `random_seed` — integer
