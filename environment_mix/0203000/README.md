# Google Workspace Server — local MCP environment

This backend models a Google Workspace integration server focused on Gmail and Google Calendar operations. It stores connected Workspace accounts, synchronized email metadata with label state, calendar events, and an audit trail of API operations so that listing/searching/modifying emails and listing/creating/updating/deleting events can be executed and tracked reliably.

Repository: https://github.com/geobio/gsuite-mcp
Homepage: https://smithery.ai/server/@geobio/gsuite-mcp

## Datastore

- `workspace_accounts.json` — Connected Google Workspace identities (one per Google user) with OAuth credentials and sync state used to call Gmail and Calendar APIs. (12 rows; fields: ['id', 'google_user_id', 'primary_email', 'display_name', 'domain', 'scopes', 'oauth_refresh_token_ciphertext', 'oauth_access_token_ciphertext', 'oauth_access_token_expires_at', 'gmail_history_id', 'last_gmail_sync_at', 'last_calendar_sync_at', 'status', 'status_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error', 'disabled']
  - constraint: unique(google_user_id)
  - constraint: unique(primary_email)
  - constraint: primary_email must contain '@'
  - constraint: oauth_access_token_expires_at is required if oauth_access_token_ciphertext is set
- `emails.json` — Gmail message metadata and server-side label/read/trash state required to list/search and modify emails without storing full message bodies. (18 rows; fields: ['id', 'account_id', 'gmail_message_id', 'gmail_thread_id', 'rfc822_message_id', 'from_email', 'to_emails', 'cc_emails', 'subject', 'snippet', 'internal_date', 'size_estimate_bytes', 'label_ids', 'is_read', 'is_archived', 'is_trashed', 'is_draft', 'status', 'last_modified_via_tool_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, gmail_message_id)
  - constraint: size_estimate_bytes is null or size_estimate_bytes >= 0
  - constraint: label_ids must be an array of distinct strings
  - constraint: is_read == (NOT contains(label_ids, 'UNREAD'))
- `email_outbox.json` — Queued/sent email compose actions for send_email, including delivery status and Gmail sent message linkage. (19 rows; fields: ['id', 'account_id', 'to_emails', 'cc_emails', 'bcc_emails', 'subject', 'body_text', 'body_html', 'reply_to', 'in_reply_to_rfc822_message_id', 'gmail_sent_message_id', 'status', 'error_code', 'error_message', 'attempt_count', 'last_attempt_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'sending', 'sent', 'failed', 'cancelled']
  - constraint: attempt_count >= 0
  - constraint: to_emails must be non-empty array
  - constraint: at least one of body_text or body_html must be non-null
  - constraint: gmail_sent_message_id is required when status == 'sent'
- `calendar_events.json` — Calendar event records mirrored from Google Calendar and created/updated/deleted through tools. (19 rows; fields: ['id', 'account_id', 'calendar_id', 'google_event_id', 'ical_uid', 'summary', 'description', 'location', 'start_at', 'end_at', 'timezone', 'is_all_day', 'attendees', 'conference_data', 'status', 'visibility', 'etag', 'created_at', 'updated_at'])
  - lifecycle `status`: ['confirmed', 'cancelled', 'deleted']
  - constraint: unique(account_id, calendar_id, google_event_id)
  - constraint: end_at > start_at
  - constraint: calendar_id is non-empty
  - constraint: visibility is null or visibility in ('default','public','private','confidential')
- `api_operations.json` — Audit log of tool invocations and underlying Google API calls for observability, debugging, and rate/quota enforcement. (18 rows; fields: ['id', 'account_id', 'tool_name', 'request_payload', 'response_payload', 'provider', 'provider_method', 'http_status', 'duration_ms', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'retried']
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: error_message is required when status == 'failed'

## Business rules enforced by the tools

- All tools operate in the context of exactly one workspace_accounts row determined by the server session; any read/write must scope by account_id.
- list_emails returns emails where emails.status == 'active' for the session account, ordered by internal_date desc, and must not return emails from other accounts.
- search_emails executes a provider search and/or local filter over emails for the session account; any stored search query string must be recorded in api_operations.request_payload.query.
- modify_email must only update emails belonging to the session account; it updates label_ids and derived booleans (is_read/is_archived/is_trashed) atomically and sets last_modified_via_tool_at.
- send_email creates an email_outbox row in status 'queued' then transitions through 'sending' to 'sent' or 'failed'; attempt_count increments on each provider attempt and is capped at 10.
- When email_outbox.status becomes 'sent', email_outbox.gmail_sent_message_id must be set and an api_operations row must be written with tool_name == 'send_email' and status == 'succeeded'.
- list_events returns calendar_events for the session account with status != 'deleted' and start_at >= now() - 1 day, ordered by start_at asc.
- create_event inserts a calendar_events row with a new google_event_id from provider and status 'confirmed' (or 'cancelled' if provider returns cancelled) and records the operation in api_operations.
- update_event may only mutate calendar_events where account_id matches and status != 'deleted'; optimistic concurrency uses etag when present and must fail with a logged api_operations status 'failed' on etag mismatch.
- delete_event transitions calendar_events.status to 'deleted' (soft delete) and must also record the provider delete call in api_operations; hard deletes are not allowed.
- workspace_accounts.status must be 'active' for any tool call; if status in ('revoked','disabled'), tools must reject and log api_operations with status 'failed'.
- Rate limiting/quota enforcement: per account, no more than 300 api_operations per 60 seconds; excess calls must be rejected and logged with error_code 'rate_limited'.