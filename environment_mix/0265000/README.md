# Mem0 Memory Server — local MCP environment

This backend stores user/agent "memories" (text plus optional structured metadata) and provides fast search over them, while also recording operational traces of environment introspection (process tree) and command executions. The main workflows are: create/update memories, run searches that return ranked matches, and log/securely audit any environment/OS interactions initiated via the API.

Repository: https://github.com/big-omega/mem0-mcp
Homepage: https://smithery.ai/server/@big-omega/mem0-mcp

## Datastore

- `api_keys.json` — Authentication and tenancy boundary for the Mem0 Memory Server. Keys are used to attribute and rate-limit memory operations and to audit environment/command tools. (18 rows; fields: ['id', 'key_hash', 'label', 'owner_principal', 'status', 'last_used_at', 'daily_search_limit', 'daily_add_limit', 'daily_exec_limit', 'daily_proc_tree_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_search_limit >= 0
  - constraint: daily_add_limit >= 0
  - constraint: daily_exec_limit >= 0
- `memories.json` — Canonical store of memories. Each memory is a text blob with optional structured metadata and an embedding for similarity search. (20 rows; fields: ['id', 'api_key_id', 'source', 'content', 'metadata', 'content_sha256', 'embedding', 'embedding_model', 'status', 'archived_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: unique(api_key_id, content_sha256) where status != 'deleted'
  - constraint: content length(content) between 1 and 65535
  - constraint: embedding is null OR array_length(embedding) between 128 and 4096
- `memory_searches.json` — Audit log of search-memories calls. Stores the query payload (even if the tool surface has no parameters), execution metrics, and status. (18 rows; fields: ['id', 'api_key_id', 'query_text', 'query_payload', 'top_k', 'latency_ms', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'succeeded', 'failed']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: top_k between 1 and 50
  - constraint: latency_ms is null OR latency_ms >= 0
- `memory_search_results.json` — Ranked results for a given memory search. Enables deterministic replay, debugging, and analytics. (18 rows; fields: ['id', 'search_id', 'memory_id', 'rank', 'score', 'snippet', 'created_at', 'updated_at'])
  - lifecycle `rank`: []
  - constraint: foreign key (search_id) references memory_searches(id) on delete cascade
  - constraint: foreign key (memory_id) references memories(id)
  - constraint: unique(search_id, rank)
  - constraint: unique(search_id, memory_id)
- `system_tool_runs.json` — Audit and control-plane table for environment tools: get-process-tree and execute-command. Stores the request, output, exit codes, and enforces policy/quota. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'request_payload', 'command', 'status', 'exit_code', 'stdout', 'stderr', 'process_tree_text', 'latency_ms', 'blocked_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'blocked']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: tool_name in ('get-process-tree','execute-command')
  - constraint: command is not null when tool_name='execute-command'
  - constraint: command is null when tool_name='get-process-tree'

## Business rules enforced by the tools

- Each tool invocation must be attributed to exactly one api_keys.id; requests with api_keys.status != 'active' must be rejected or recorded as system_tool_runs.status='blocked' / memory_searches.status='failed'.
- add-memory must create one memories row with status='active', non-empty content, and a computed content_sha256; if a non-deleted memory already exists for the same (api_key_id, content_sha256), the server must not create a duplicate and should return the existing memory id.
- search-memories must create one memory_searches row per call (status transitions running -> succeeded/failed) and up to top_k memory_search_results rows, with unique (search_id, rank) and unique (search_id, memory_id).
- search-memories must only return memories where memories.api_key_id matches the caller and memories.status != 'deleted'. Archived memories may be included or excluded by server policy, but the policy must be consistent and recorded in memory_searches.query_payload.
- get-process-tree must create a system_tool_runs row with tool_name='get-process-tree' and populate process_tree_text on success; command must be null for this tool.
- execute-command must create a system_tool_runs row with tool_name='execute-command', store the command string, and capture stdout/stderr/exit_code; outputs must be truncated to configured maximum lengths and recorded as such in request_payload or blocked_reason.
- Daily quotas must be enforced per api_key_id: search-memories calls count against daily_search_limit; add-memory against daily_add_limit; execute-command against daily_exec_limit; get-process-tree against daily_proc_tree_limit. Over-limit requests must be rejected or recorded as status='blocked' with blocked_reason='quota_exceeded'.
- No record may transition out of a terminal status: api_keys.revoked, memories.deleted, memory_searches.succeeded/failed, and system_tool_runs.succeeded/failed/blocked are terminal.
- Foreign key integrity must be enforced: deleting an api_keys row is not allowed if referenced by memories/memory_searches/system_tool_runs; deleting a memory_searches row must cascade-delete its memory_search_results.