# Google Tasks Integration Server — local MCP environment

This backend persists local representations of Google Tasks tasklists and tasks, plus the OAuth2 connection state needed to call Google on behalf of a user. Main workflows are: authenticate via OAuth, store/refresh tokens, then CRUD tasklists and tasks (including completing, moving/reordering, and clearing completed tasks) while keeping local state consistent with Google resource IDs and ordering.

Repository: https://github.com/arpitbatra123/mcp-googletasks
Homepage: https://smithery.ai/server/@arpitbatra123/mcp-googletasks

## Datastore

- `accounts.json` — Represents a single connected Google identity (or local user) using the integration. Owns OAuth connection state and the imported task data. (18 rows; fields: ['id', 'google_user_id', 'email', 'display_name', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending_auth', 'active', 'revoked', 'error']
  - constraint: unique(google_user_id) where google_user_id is not null
  - constraint: unique(email) where email is not null
  - constraint: created_at <= updated_at
- `oauth_connections.json` — OAuth2 authorization artifacts (auth code exchange results, refresh/access tokens, scopes, expiry) used to call Google Tasks APIs on behalf of an account. (18 rows; fields: ['id', 'account_id', 'provider', 'status', 'auth_code_hash', 'code_received_at', 'access_token_ciphertext', 'refresh_token_ciphertext', 'scopes', 'token_expires_at', 'last_token_refresh_at', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['needs_consent', 'code_received', 'token_active', 'token_expired', 'revoked', 'error']
  - constraint: unique(account_id, provider)
  - constraint: array_length(scopes) >= 1
  - constraint: token_expires_at is null or token_expires_at > created_at
  - constraint: auth_code_hash is null or length(auth_code_hash) >= 32
- `tasklists.json` — Local mirror of Google Tasks TaskList resources per account. (17 rows; fields: ['id', 'account_id', 'google_tasklist_id', 'title', 'status', 'etag', 'self_link', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'archived']
  - constraint: unique(account_id, google_tasklist_id)
  - constraint: title <> ''
  - constraint: created_at <= updated_at
  - constraint: fk(account_id) references accounts(id) on delete cascade
- `tasks.json` — Local mirror of Google Tasks Task resources, including ordering/move metadata and completion state. (19 rows; fields: ['id', 'account_id', 'tasklist_id', 'google_task_id', 'title', 'notes', 'status', 'due_at', 'completed_at', 'deleted_at', 'parent_task_id', 'position', 'sort_index', 'etag', 'self_link', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['needs_action', 'completed', 'deleted']
  - constraint: unique(tasklist_id, google_task_id)
  - constraint: title <> ''
  - constraint: sort_index >= 0
  - constraint: completed_at is null or status = 'completed'
- `api_requests.json` — Audit log of tool calls and Google API interactions for troubleshooting, quota tracking, and idempotency. (20 rows; fields: ['id', 'account_id', 'tool_name', 'status', 'request_payload', 'response_payload', 'error_message', 'provider_http_status', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'succeeded', 'failed']
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: provider_http_status is null or (provider_http_status >= 100 and provider_http_status <= 599)
  - constraint: created_at <= updated_at
  - constraint: fk(account_id) references accounts(id) on delete set null

## Business rules enforced by the tools

- authenticate creates (or reuses) an accounts row with status='pending_auth' and an oauth_connections row with provider='google' and status='needs_consent'; it must also create an api_requests row for auditing.
- set-auth-code requires an existing oauth_connections row in status in ('needs_consent','error'); it stores only a hash of the provided auth code, sets code_received_at, and transitions status to 'code_received'.
- Token exchange/refresh (performed as part of any tool that calls Google) must only transition oauth_connections.status to 'token_active' when access_token_ciphertext is set and token_expires_at is in the future; if refresh fails with invalid_grant, transition to 'revoked'.
- list-tasklists returns all tasklists for the resolved account where status != 'deleted', ordered by updated_at desc (or provider order if available).
- get-tasklist requires the requested tasklist to belong to the resolved account; otherwise return not found.
- create-tasklist inserts tasklists(status='active') with a unique (account_id, google_tasklist_id) after provider creation; title is required and non-empty.
- update-tasklist may only update title/etag/self_link and must not modify google_tasklist_id; if the tasklist is deleted, the operation must fail.
- delete-tasklist must soft-delete locally by setting status='deleted' and may cascade delete to tasks (either hard delete or set tasks.status='deleted'); subsequent reads must not return deleted entities.
- list-tasks returns tasks in a given tasklist where status != 'deleted'; ordering uses provider position when present, else sort_index ascending; it must enforce that tasklist_id belongs to the resolved account.
- get-task requires the task to belong to the resolved account and tasklist; otherwise return not found.
- create-task inserts tasks(status='needs_action', sort_index=max(sort_index)+1 within the tasklist) after provider creation; parent_task_id, if set, must reference a task in the same tasklist.
- update-task may change title, notes, due_at, parent_task_id, and ordering metadata; it must reject updates that would create a parent cycle (a task cannot be its own ancestor).
- delete-task transitions tasks.status to 'deleted' and sets deleted_at; it must be idempotent (deleting an already deleted task leaves it deleted).
- complete-task transitions tasks.status to 'completed' and sets completed_at=now; repeating complete-task is idempotent and must not clear completed_at.
- move-task must keep all tasks within a tasklist with unique, strictly increasing sort_index; it updates sort_index (and optionally position) for the moved task and may renormalize neighboring tasks if required.
- clear-completed-tasks must remove all tasks with status='completed' for a given tasklist: either hard-delete rows or set status='deleted' and deleted_at; it must not affect tasks with status='needs_action'.
- All mutating tools must write an api_requests row with tool_name, request_payload, and final status; failed provider calls must record provider_http_status and error_message.
- FK integrity: a task cannot exist without a tasklist; a tasklist cannot exist without an account; deleting an account must cascade delete its oauth_connections, tasklists, and tasks.