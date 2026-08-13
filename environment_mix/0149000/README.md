# Todoist MCP Server — local MCP environment

This backend models a lightweight Todoist-integrated task service exposed via an MCP server. It stores connected Todoist accounts, mirrors key task fields for fast search-by-name operations, and records tool invocations for auditing and idempotency across create/update/delete/complete workflows.

Repository: https://github.com/abhiz123/todoist-mcp-server
Homepage: https://smithery.ai/server/@abhiz123/todoist-mcp-server

## Datastore

- `accounts.json` — Connected Todoist accounts (one per Todoist user/token) that the MCP server can operate on; used for scoping tasks and audit logs. (12 rows; fields: ['id', 'provider', 'todoist_user_id', 'display_name', 'access_token_ciphertext', 'token_last4', 'status', 'last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: provider IN ('todoist')
  - constraint: access_token_ciphertext IS NOT NULL
  - constraint: unique(provider, todoist_user_id) WHERE todoist_user_id IS NOT NULL
  - constraint: status IN ('active','revoked','error')
- `projects.json` — Optional local mirror of Todoist projects for task association and filtering; populated lazily from Todoist task payloads. (12 rows; fields: ['id', 'account_id', 'todoist_project_id', 'name', 'color', 'is_inbox', 'is_archived', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: account_id references accounts.id
  - constraint: todoist_project_id IS NOT NULL
  - constraint: unique(account_id, todoist_project_id)
  - constraint: name <> ''
- `tasks.json` — Local mirror/index of Todoist tasks for fast name-based search and tool operations (update/delete/complete) that require locating a task by content/name. (31 rows; fields: ['id', 'account_id', 'todoist_task_id', 'project_id', 'content', 'content_normalized', 'description', 'priority', 'due_at', 'due_date', 'labels', 'assignee_todoist_user_id', 'order_index', 'status', 'completed_at', 'deleted_at', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: account_id references accounts.id
  - constraint: project_id references projects.id
  - constraint: unique(account_id, todoist_task_id)
  - constraint: content <> ''
- `task_search_index.json` — Auxiliary index rows enabling efficient search-by-name queries used by update/delete/complete. This supports prefix/substring matching and de-duplication of ambiguous names. (30 rows; fields: ['id', 'account_id', 'task_id', 'term', 'term_type', 'created_at', 'updated_at'])
  - lifecycle `term_type`: ['full', 'token', 'prefix']
  - constraint: account_id references accounts.id
  - constraint: task_id references tasks.id ON DELETE CASCADE
  - constraint: term <> ''
  - constraint: unique(account_id, task_id, term, term_type)
- `tool_invocations.json` — Audit and idempotency log for MCP tool calls. Stores inputs/outputs and links to affected task when applicable. (20 rows; fields: ['id', 'account_id', 'tool_name', 'request_payload', 'resolved_search_name', 'matched_task_id', 'status', 'error_message', 'response_payload', 'idempotency_key', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: account_id references accounts.id
  - constraint: matched_task_id references tasks.id
  - constraint: tool_name IN ('todoist_create_task','todoist_get_tasks','todoist_update_task','todoist_delete_task','todoist_complete_task')
  - constraint: duration_ms IS NULL OR duration_ms >= 0

## Business rules enforced by the tools

- All tools execute within exactly one active accounts row; if no active account is configured, the tool must fail with status=failed and set accounts.status=error only when Todoist returns an auth error.
- todoist_get_tasks reads from tasks for the account; if last_synced_at is stale (implementation-defined), the service must refresh tasks from Todoist before returning and update last_synced_at.
- todoist_create_task must create the task in Todoist first, then upsert into tasks using unique(account_id, todoist_task_id); the new row must start with status='active' and content/content_normalized populated.
- todoist_update_task must resolve a single task by name using tasks.content_normalized and/or task_search_index.term; if zero matches, fail; if multiple matches, fail unless a deterministic tie-breaker is applied (e.g., most recently updated active task).
- todoist_complete_task may transition only tasks.status: active -> completed; it must set completed_at and must not modify deleted tasks.
- todoist_delete_task may transition tasks.status: active|completed -> deleted; it must set deleted_at and must remove (or cascade delete) task_search_index rows for that task.
- Any successful mutation tool (create/update/complete/delete) must write a tool_invocations row with status='succeeded' and matched_task_id referencing the impacted task when applicable.
- For every tasks row, task_search_index must contain exactly one term_type='full' row with term = tasks.content_normalized; token/prefix rows are optional but if present must be unique per (account_id, task_id, term, term_type).
- priority, when provided, must be within 1..4; due_at and due_date may not both be set unless the vendor payload includes both (otherwise server should normalize to one).
- Status transitions must follow each collection's lifecycle.transitions; attempts to bypass transitions must be rejected and logged in tool_invocations with status='failed'.