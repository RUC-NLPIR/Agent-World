# CrescentDesk Support Console

CrescentDesk Support Console is a support ticketing service for creating, viewing, and managing business support requests for authenticated users.

## Datastore

### `state.json` — single document
Holds the service’s current operational state, including the active ticket queue, the next ticket id counter, and the currently authenticated user context, so ticket operations can be processed consistently.

- `ticket_queue` — array
  each record in `ticket_queue` has:
  - `id` — integer
  - `title` — string
  - `description` — string
  - `status` — string — one of Closed, Open, Resolved
  - `priority` — integer
  - `created_by` — string — one of alice, bob, carol, dave, eve, frank
  - `resolution` — string
- `ticket_counter` — integer
- `current_user` — string
- `random_seed` — integer
