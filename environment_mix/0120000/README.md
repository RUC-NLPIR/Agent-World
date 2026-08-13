# Voyager Session Vault

Voyager Session Vault is a service that captures and persists the current state of an interactive browser session for inspection and automation.

## Datastore

### `page_state.json` — single document
Holds a single snapshot of the current browser session (open tabs, viewport, element snapshot, console, network activity, and any active dialog) so the service can track and resume what the browser is showing and doing.

- `tabs` — array
  each record in `tabs` has:
  - `index` — integer
  - `title` — string
  - `url` — string
  - `active` — boolean
- `current_url` — string
- `title` — string
- `viewport` — object
  each record in `viewport` has:
  - `width` — integer
  - `height` — integer
- `snapshot` — array
  each record in `snapshot` has:
  - `ref` — string
  - `role` — string
  - `name` — string
- `console` — array
  each record in `console` has:
  - `type` — string — one of error, info, log, warning
  - `text` — string
- `network` — array
  each record in `network` has:
  - `method` — string — one of GET, POST
  - `url` — string
  - `status` — integer
  - `resourceType` — string — one of document, fetch, image, other
- `dialog` — object
  each record in `dialog` has:
  - `type` — string
  - `message` — string
