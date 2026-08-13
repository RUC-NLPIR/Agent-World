# Memory MCP — local MCP environment

This backend stores user-created "memories" (title + content) and supports CRUD operations via MCP tools. It also tracks API clients (for simple auth/quota) and an audit log of tool invocations for debugging, rate limiting, and compliance.

Repository: https://github.com/drdee/memory-mcp
Homepage: https://smithery.ai/server/@drdee/memory-mcp

## Datastore

- `api_clients.json` — Represents an API consumer (e.g., an MCP client instance). Used for authentication, quotas, and scoping memories to a client/tenant. (12 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'quota_memories_max', 'quota_requests_per_minute', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: quota_memories_max >= 0
  - constraint: quota_requests_per_minute >= 0
- `memories.json` — Core entity representing a stored memory (title + content). Supports create, retrieve (by id/title), list, update, and delete (soft-delete). (18 rows; fields: ['id', 'client_id', 'title', 'content', 'status', 'deleted_at', 'content_sha256', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: unique(client_id, title) where status = 'active'
  - constraint: length(title) between 1 and 300
  - constraint: length(content) >= 1
- `memory_versions.json` — Append-only version history for memories, enabling audit and rollback-like inspection. A new version is created on remember and update_memory, and a final tombstone version on delete_memory. (33 rows; fields: ['id', 'memory_id', 'version', 'title', 'content', 'content_sha256', 'change_type', 'created_by_invocation_id', 'created_at', 'updated_at'])
  - lifecycle `change_type`: ['create', 'update', 'delete']
  - constraint: fk(memory_id) references memories(id) on delete cascade
  - constraint: unique(memory_id, version)
  - constraint: version >= 1
  - constraint: content_sha256 matches /^[A-Fa-f0-9]{64}$/
- `tool_invocations.json` — Request/response audit log for MCP tool calls. Enables rate limiting, debugging, and traceability of writes. (34 rows; fields: ['id', 'client_id', 'tool_name', 'status', 'request_params', 'response_summary', 'error_message', 'related_memory_id', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: duration_ms >= 0

## Business rules enforced by the tools

- remember(title, content) creates a new memories row with status='active' and a corresponding memory_versions row with change_type='create' and version=1.
- remember must enforce per-client quotas: count(memories where client_id=? and status='active') < api_clients.quota_memories_max; otherwise reject with a quota error and log a failed tool_invocations row.
- get_memory(memory_id, title) requires exactly one of memory_id or title to be provided; if both are provided, the service rejects the request and logs a failed invocation.
- get_memory by title searches within the caller's client_id scope and only returns memories with status='active'.
- list_memories returns only memories with status='active' for the caller's client_id, ordered by updated_at desc (or created_at desc as fallback).
- update_memory(memory_id, title?, content?) requires at least one of title or content be provided; otherwise reject and log a failed invocation.
- update_memory must not modify memories where status='deleted'. Attempts must fail and be logged.
- update_memory writes changes to memories.title/content/content_sha256, bumps updated_at, and appends a memory_versions row with version = (max(version)+1) and change_type='update'.
- delete_memory(memory_id) performs a soft delete: set memories.status='deleted', set deleted_at=now, bump updated_at, and append a memory_versions row with change_type='delete' containing the final snapshot.
- Unique active title per client is enforced: (client_id, title) must be unique among memories with status='active'; update_memory must fail if it would violate this constraint.
- All tool calls must be logged in tool_invocations with tool_name, request_params, status, and duration_ms; successful write operations should populate related_memory_id and, when applicable, memory_versions.created_by_invocation_id.