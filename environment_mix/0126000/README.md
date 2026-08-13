# Memory Tool — local MCP environment

This backend stores user/agent "memories" (short text facts, preferences, and notes) and supports two workflows: adding a new memory and searching existing memories. A lightweight indexing pipeline maintains searchable representations of memories and records each search for auditing and potential ranking/quality improvements.

Repository: https://github.com/mem0ai/mem0-mcp
Homepage: https://smithery.ai/server/@mem0ai/mem0-memory-mcp

## Datastore

- `workspaces.json` — Tenant boundary for memories. In a real deployment this maps to an app/org/project where an agent runs. API/auth would typically scope to a workspace even if the tool surface does not expose it. (12 rows; fields: ['id', 'name', 'status', 'default_retention_days', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_retention_days >= 0 and default_retention_days <= 36500
- `actors.json` — Represents the caller/agent/user identity that adds and searches memories. Even if the tool parameters are empty, a real system associates requests to an authenticated actor. (12 rows; fields: ['id', 'workspace_id', 'type', 'external_ref', 'display_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: foreign key (workspace_id) references workspaces(id)
  - constraint: unique(workspace_id, external_ref) where external_ref is not null
- `memories.json` — Primary stored memory items. add-memory inserts into this table. search-memories reads from this table (often via memory_index) filtered by workspace/actor and lifecycle. (18 rows; fields: ['id', 'workspace_id', 'actor_id', 'source', 'content', 'content_hash', 'metadata', 'importance', 'expires_at', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'expired', 'deleted']
  - constraint: foreign key (workspace_id) references workspaces(id)
  - constraint: foreign key (actor_id) references actors(id)
  - constraint: unique(workspace_id, actor_id, content_hash) where status != 'deleted'
  - constraint: importance >= 0 and importance <= 1
- `memory_index.json` — Search/index representation for each memory (embedding vector and/or full-text tokens). search-memories primarily queries this table and joins back to memories for filtering and returning content. (18 rows; fields: ['id', 'memory_id', 'workspace_id', 'actor_id', 'index_version', 'embedding_model', 'embedding', 'tsv', 'status', 'last_indexed_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'ready', 'stale', 'failed']
  - constraint: foreign key (memory_id) references memories(id) on delete cascade
  - constraint: foreign key (workspace_id) references workspaces(id)
  - constraint: foreign key (actor_id) references actors(id)
  - constraint: unique(memory_id)
- `search_requests.json` — Audit log of search-memories calls (including empty/implicit queries) for observability, quota enforcement, and ranking improvements. (18 rows; fields: ['id', 'workspace_id', 'actor_id', 'query_text', 'top_k', 'filter', 'results_count', 'latency_ms', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'error']
  - constraint: foreign key (workspace_id) references workspaces(id)
  - constraint: foreign key (actor_id) references actors(id)
  - constraint: top_k >= 1 and top_k <= 100
  - constraint: results_count >= 0 and results_count <= top_k

## Business rules enforced by the tools

- add-memory must insert a row into memories with source='tool:add-memory', status='active', and set content_hash from normalized content; if a non-deleted memory exists with the same (workspace_id, actor_id, content_hash), the service must not create a duplicate and should instead return the existing memory id (idempotency).
- After add-memory, the system must upsert memory_index for that memory_id with status='pending' (or 'stale') to trigger (re)indexing; once indexing completes it must transition to status='ready' and set last_indexed_at.
- search-memories must only return memories where memories.status='active' and (expires_at is null or expires_at > now()) and workspace.status='active' and actor.status='active'.
- search-memories must log every call by inserting into search_requests with status='ok' or 'error' and with top_k defaulting to 10 when not provided by runtime.
- A memory may transition from active->expired automatically when expires_at <= now(); expired memories must be excluded from search results (same as deleted).
- FK integrity must be enforced: memories.workspace_id must match actors.workspace_id for the referenced actor; writes violating this must be rejected.
- Quota/abuse limits (even if not exposed as tool params) must be enforced per workspace: maximum 100,000 active memories per workspace and maximum 60 search_requests per minute per actor (rate limit implemented outside SQL but recorded/derivable from search_requests).
- Deleting a memory (internal operation) must set memories.status='deleted' and deleted_at, and must cascade-delete or invalidate its memory_index row (on delete cascade or by setting index status='stale').