# Mailbox Archive Gateway

Mailbox Archive Gateway is a small service for loading and retrieving email dataset records from a JSON store and related sample message artifacts.

## Datastore

### `emails.json` — list of 5 records
Holds individual email objects (metadata, body, attachments, and read flag) so the service can list emails and fetch a specific email by its email_id.

- `email_id` — string — one of email-001, email-002, email-003, email-004, email-005
- `folder` — string — one of INBOX, Sent
- `from` — string
- `to` — string
- `subject` — string
- `date` — string
- `body` — string
- `attachments` — array
- `read` — boolean
