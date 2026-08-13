# Google Workspace Server — local MCP environment

This backend stores a minimal representation of a Google Workspace-integrated mailbox and calendar for one or more connected users, including messages, labels/state changes, and calendar events. The main workflows are: listing/searching emails, sending emails (outbound + delivery status), modifying email state via labels/system flags, and listing/creating/updating/deleting calendar events.

Repository: https://github.com/rishipradeep-think41/gsuite-mcp
Homepage: https://smithery.ai/server/@rishipradeep-think41/gsuite-mcp

## Datastore

- `workspace_accounts.json` — Connected Google Workspace identities (one per Google user) including OAuth linkage metadata used to call Gmail/Calendar APIs on the user's behalf. (12 rows; fields: ['id', 'google_user_id', 'primary_email', 'display_name', 'scopes', 'token_ref', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error', 'disabled']
  - constraint: unique(google_user_id)
  - constraint: unique(primary_email)
  - constraint: primary_email LIKE '%@%'
  - constraint: scopes length >= 1
- `emails.json` — Gmail message metadata plus minimal content needed for listing/search and for tracking outbound sends. (20 rows; fields: ['id', 'account_id', 'gmail_message_id', 'thread_id', 'direction', 'from_email', 'to_emails', 'cc_emails', 'bcc_emails', 'subject', 'snippet', 'body_text', 'body_html', 'internal_date', 'is_read', 'is_archived', 'is_trashed', 'label_ids', 'status', 'provider_etag', 'created_at', 'updated_at'])
  - lifecycle `status`: ['synced', 'queued', 'sending', 'sent', 'failed', 'deleted']
  - constraint: foreign key(account_id) references workspace_accounts(id) on delete cascade
  - constraint: unique(account_id, gmail_message_id) where gmail_message_id is not null
  - constraint: from_email LIKE '%@%'
  - constraint: all elements in to_emails/cc_emails/bcc_emails LIKE '%@%'
- `email_mutations.json` — Append-only log of label/state mutations applied to emails (archive/trash/mark read/unread) to support auditability and retries. (19 rows; fields: ['id', 'account_id', 'email_id', 'mutation_type', 'add_label_ids', 'remove_label_ids', 'status', 'error_message', 'provider_request_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'applied', 'failed', 'cancelled']
  - constraint: foreign key(account_id) references workspace_accounts(id) on delete cascade
  - constraint: foreign key(email_id) references emails(id) on delete cascade
  - constraint: email.account_id must equal email_mutations.account_id (enforced in service layer)
  - constraint: array_length(add_label_ids) >= 0 and array_length(remove_label_ids) >= 0
- `calendar_events.json` — Calendar event records for connected accounts. Stores provider ids and fields necessary for list/create/update/delete operations. (19 rows; fields: ['id', 'account_id', 'calendar_id', 'google_event_id', 'title', 'description', 'location', 'start_at', 'end_at', 'time_zone', 'attendees', 'organizer_email', 'visibility', 'status', 'provider_etag', 'created_at', 'updated_at'])
  - lifecycle `status`: ['confirmed', 'tentative', 'cancelled', 'deleted']
  - constraint: foreign key(account_id) references workspace_accounts(id) on delete cascade
  - constraint: unique(account_id, calendar_id, google_event_id) where google_event_id is not null
  - constraint: end_at > start_at
  - constraint: title <> ''
- `calendar_event_mutations.json` — Mutation log for calendar operations (create/update/delete) to support auditability, retries, and idempotency. (18 rows; fields: ['id', 'account_id', 'event_id', 'mutation_type', 'patch', 'status', 'idempotency_key', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'applied', 'failed', 'cancelled']
  - constraint: foreign key(account_id) references workspace_accounts(id) on delete cascade
  - constraint: foreign key(event_id) references calendar_events(id) on delete set null
  - constraint: unique(account_id, idempotency_key) where idempotency_key is not null
  - constraint: mutation_type='create' implies event_id is null OR event_id references a draft row (enforced in service layer)

## Business rules enforced by the tools

- All tools operate in the context of exactly one active workspace_accounts row; if multiple are configured, the service must select a default account or require configuration, otherwise return an error.
- list_emails returns emails for the active account where status in ('synced','sent') and is_trashed=false, ordered by internal_date desc (fallback created_at desc).
- search_emails filters emails by an advanced query string; the service must translate the query into provider search or into DB filters over subject/snippet/body_text/from_email/to_emails/label_ids/internal_date and must only return rows for the active account.
- send_email creates an emails row with direction='outbound', status='queued', from_email=workspace_accounts.primary_email, and required recipients; after provider acceptance it must set gmail_message_id, label_ids include 'SENT', and status transitions to 'sent' (or 'failed' on error).
- modify_email must create an email_mutations row (status='queued') and apply it idempotently to the provider; on success it must update emails.label_ids and derived flags (is_read/is_archived/is_trashed) and mark the mutation 'applied'.
- Archive/unarchive semantics: archive removes 'INBOX' from label_ids; unarchive adds 'INBOX' unless is_trashed=true.
- Trash/untrash semantics: trash adds 'TRASH' and sets is_trashed=true; untrash removes 'TRASH' and sets is_trashed=false; deleting (hard) is modeled as emails.status='deleted' and must not be returned by list/search.
- Mark read/unread semantics: mark_read removes 'UNREAD' and sets is_read=true; mark_unread adds 'UNREAD' and sets is_read=false.
- list_events returns calendar_events for the active account where status != 'deleted' and end_at >= now(), ordered by start_at asc; may default calendar_id='primary'.
- create_event must write a calendar_event_mutations row (queued) then create/overwrite a calendar_events row (google_event_id assigned after provider creation). It must enforce end_at > start_at and non-empty title.
- update_event must verify the target calendar_events row belongs to the active account; it must apply optimistic concurrency using provider_etag when available, then update the row and append a calendar_event_mutations record marked applied/failed.
- delete_event must set calendar_events.status='deleted' (and/or 'cancelled' depending on provider semantics) and append a calendar_event_mutations record; subsequent list_events must not return deleted events.
- FK integrity must be enforced: any emails/account_id, email_mutations/email_id, calendar_events/account_id references must exist at write time; cross-account mutation (mutation.account_id != target.account_id) must be rejected.
- Quota/rate limiting (if implemented at the service edge) must prevent more than N queued mutations per account (configured limit), otherwise mutation creation must be rejected with a retriable error.