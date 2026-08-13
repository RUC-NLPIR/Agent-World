# Orchard Contact Exchange

Orchard Contact Exchange is a lightweight directory and messaging service for looking up organizational contacts and exchanging simulated messages with them.

## Datastore

### `contacts.json` — list of 120 records
Holds individual people records so the service can retrieve and search contacts and address messages to a specific contact.

- `contact_id` — string
- `name` — string
- `email` — string
- `phone` — string
- `department_id` — string

### `departments.json` — list of 10 records
Holds department records so the service can present departmental context for contacts and support listing departments.

- `department_id` — string
- `name` — string
- `head` — string
