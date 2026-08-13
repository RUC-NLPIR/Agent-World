# Google Workspace MCP Server — local MCP environment

This backend models a lightweight Google Workspace connector that lets authenticated users list/search/modify Gmail messages and list/create/update/delete Google Calendar events. It stores linked Google identities, OAuth credentials, cached message/event metadata, and an audit log of tool calls to support traceability, quotas, and idempotent writes.

Repository: https://github.com/epaproditus/google-workspace-mcp-server
Homepage: https://smithery.ai/server/google-workspace-server

## Datastore

- `workspaces.json` — Tenant/workspace boundary for the MCP server. Holds basic org settings and provides a scope for identities, cached objects, and audit logs. (12 rows; fields: ['id', 'name', 'status', 'default_timezone', 'retention_days', 'daily_tool_call_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: retention_days BETWEEN 1 AND 3650
  - constraint: daily_tool_call_quota BETWEEN 0 AND 1000000
- `google_identities.json` — A linked Google account (Gmail/Calendar) used to perform actions. Stores OAuth tokens and per-identity settings. (35 rows; fields: ['id', 'workspace_id', 'google_user_id', 'primary_email', 'display_name', 'oauth_access_token', 'oauth_refresh_token', 'oauth_token_expiry', 'scopes', 'gmail_history_id', 'calendar_sync_token', 'status', 'last_auth_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'needs_reauth', 'revoked', 'deleted']
  - constraint: unique(workspace_id, google_user_id)
  - constraint: unique(workspace_id, primary_email)
  - constraint: oauth_token_expiry > created_at
  - constraint: array_length(scopes) >= 1
- `gmail_messages.json` — Cached Gmail message metadata used to serve list/search results quickly and support label modifications (archive/trash/read/unread). Body is optionally cached; source of truth remains Gmail. (36 rows; fields: ['id', 'workspace_id', 'identity_id', 'gmail_message_id', 'gmail_thread_id', 'rfc822_message_id', 'subject', 'from', 'to', 'cc', 'snippet', 'internal_date', 'labels', 'is_read', 'is_trashed', 'is_archived', 'raw_mime_b64', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(identity_id, gmail_message_id)
  - constraint: internal_date IS NULL OR internal_date <= updated_at
  - constraint: labels IS NOT NULL
  - constraint: is_read = (NOT array_contains(labels, 'UNREAD'))
- `calendar_events.json` — Cached Calendar events and locally initiated event writes. Supports listing upcoming events and CRUD operations mapped to Google Calendar events. (36 rows; fields: ['id', 'workspace_id', 'identity_id', 'google_calendar_id', 'google_event_id', 'ical_uid', 'title', 'description', 'location', 'start_time', 'end_time', 'timezone', 'attendees', 'conference_data', 'etag', 'status', 'write_state', 'last_error', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `write_state`: ['synced', 'pending_create', 'pending_update', 'pending_delete', 'error']
  - constraint: end_time > start_time
  - constraint: unique(identity_id, google_calendar_id, google_event_id)
  - constraint: google_event_id IS NOT NULL OR write_state = 'pending_create'
  - constraint: status IN ('scheduled','cancelled','deleted','tombstoned')
- `tool_calls.json` — Audit log of MCP tool invocations (read and write). Used for debugging, quota enforcement, idempotency of write operations, and tracking which cached objects were touched. (40 rows; fields: ['id', 'workspace_id', 'identity_id', 'tool_name', 'request_params', 'idempotency_key', 'status', 'http_status', 'error_code', 'error_message', 'result_summary', 'touched_gmail_message_ids', 'touched_calendar_event_ids', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: unique(workspace_id, tool_name, idempotency_key) WHERE idempotency_key IS NOT NULL
  - constraint: http_status BETWEEN 100 AND 599 OR http_status IS NULL
  - constraint: finished_at IS NULL OR started_at IS NOT NULL
  - constraint: finished_at IS NULL OR finished_at >= started_at

## Business rules enforced by the tools

- All tool executions must be associated with exactly one workspace; identity_id is required for Gmail and Calendar tools unless operating in a configured single-identity mode.
- If google_identities.status != 'active', any tool call that requires Google API access must fail with status='failed' and set error_code='needs_reauth' or 'revoked' accordingly.
- Workspace quota enforcement: the number of tool_calls with status in ('succeeded','failed') per workspace per UTC day must not exceed workspaces.daily_tool_call_quota; excess calls must be rejected before contacting Google.
- list_emails must read from gmail_messages for the identity when available; if cache is stale (last_synced_at older than retention policy or missing), the implementation must fetch from Gmail and upsert gmail_messages by (identity_id, gmail_message_id).
- search_emails must persist an audit record in tool_calls and may filter cached gmail_messages; if cache coverage is insufficient, it must query Gmail and upsert results into gmail_messages.
- send_email must create a tool_calls row with an idempotency_key when provided by the client; repeated send_email with the same (workspace_id, tool_name, idempotency_key) must return the original result_summary and must not send duplicate emails.
- modify_email must only change gmail_messages.labels/is_read/is_trashed/is_archived in ways consistent with Gmail semantics: marking read removes 'UNREAD'; marking unread adds 'UNREAD'; trash adds 'TRASH' and removes 'INBOX'; archive removes 'INBOX' without adding 'TRASH'.
- list_events must return events from calendar_events for the identity/calendar in the requested time window (or upcoming), refreshing from Google when last_synced_at is stale; it must update google_identities.calendar_sync_token when incremental sync is performed.
- create_event must insert a calendar_events row with write_state='pending_create' then attempt Google create; on success set google_event_id, etag, write_state='synced'; on failure set write_state='error' and last_error.
- update_event must require a resolvable target event (by google_event_id or internal id) and set write_state='pending_update' before calling Google; if etag is present, the update must be conditional to prevent lost updates.
- delete_event must set write_state='pending_delete' before calling Google; on success set status='deleted' and write_state='synced' (or remove google_event_id and mark tombstoned per retention policy).
- FK integrity: deleting a workspace must cascade to google_identities, gmail_messages, calendar_events, and tool_calls (or mark them deleted) so no orphan rows remain.