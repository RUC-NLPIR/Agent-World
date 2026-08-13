# PostHaven Mailbox Manager

PostHaven Mailbox Manager is a mailbox service for managing user email accounts and their per-folder messages, including listing folders, retrieving and searching messages, sending mail, and clearing folders.

## Datastore

### `email_accounts.json` — object of 20 records keyed by identifier
Stores mailbox login identities (display name and password) so the service can address operations to a specific email account.
Keys look like: chen.jie@acme-qc.com, liu.yang@acme-qc.com, zhao.min@acme-qc.com

- `name` — string
- `password` — string

### `mailboxes.json` — object of 20 records keyed by identifier
Stores each account’s mailbox folders (e.g., INBOX, Sent, Drafts, Trash, Archive) and the messages within them so the service can organize, search, send, and purge email by folder.
Keys look like: chen.jie@acme-qc.com, liu.yang@acme-qc.com, zhao.min@acme-qc.com

- `INBOX` — array
  each record in `INBOX` has:
  - `id` — integer
  - `from` — string
  - `to` — string
  - `subject` — string
  - `body` — string
  - `date` — string
  - `folder` — string
  - `thread_id` — string
  - `attachments` — array
    each record in `attachments` has:
    - `filename` — string
    - `size_kb` — integer
  - `in_reply_to` — integer
  - `cc` — string
- `Sent` — array
  each record in `Sent` has:
  - `id` — integer
  - `from` — string
  - `to` — string
  - `subject` — string
  - `body` — string
  - `date` — string
  - `folder` — string
  - `in_reply_to` — integer
  - `thread_id` — string
  - `cc` — string
  - `attachments` — array
    each record in `attachments` has:
    - `filename` — string
    - `size_kb` — integer
- `Drafts` — array
  each record in `Drafts` has:
  - `id` — integer
  - `from` — string
  - `to` — string
  - `subject` — string
  - `body` — string
  - `date` — string
  - `folder` — string
  - `thread_id` — string
- `Trash` — array
  each record in `Trash` has:
  - `id` — integer
  - `from` — string
  - `to` — string
  - `subject` — string
  - `body` — string
  - `date` — string
  - `folder` — string
  - `thread_id` — string — one of thr-stock-0, thr-stock-1, thr-stock-2
- `Archive` — array
  each record in `Archive` has:
  - `id` — integer
  - `from` — string
  - `to` — string
  - `subject` — string
  - `body` — string
  - `date` — string
  - `folder` — string
  - `thread_id` — string — one of thr-240301, thr-po4460
