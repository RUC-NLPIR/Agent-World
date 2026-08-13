# Think Tool Server — local MCP environment

This backend stores append-only "thought" logs created via the think tool, along with the actor identity (API key) and the logical tenant/workspace that owns the entries. The primary workflow is: authenticate an API key, append a thought entry to a workspace log, and optionally review usage and audit history.

Repository: https://github.com/PhillipRt/think-mcp-server
Homepage: https://smithery.ai/server/@PhillipRt/think-mcp-server

## Datastore

- `workspaces.json` — Tenant container for thought logs and API keys. Enables per-tenant quota and isolation. (12 rows; fields: ['id', 'name', 'status', 'retention_days', 'max_thought_chars', 'daily_thought_limit', 'daily_char_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: retention_days BETWEEN 1 AND 3650
  - constraint: max_thought_chars BETWEEN 1 AND 200000
  - constraint: daily_thought_limit BETWEEN 1 AND 1000000
- `api_keys.json` — API keys used to authenticate callers for the think tool. Keys belong to a workspace and are used for auditing and quota enforcement. (11 rows; fields: ['id', 'workspace_id', 'name', 'status', 'key_prefix', 'key_hash', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, workspace_id)
- `thought_logs.json` — Append-only log of thoughts submitted via the think tool. This is the direct persistence for the tool parameter `thought`. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'thought', 'thought_sha256', 'thought_chars', 'client_request_id', 'ip_address', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'redacted', 'deleted']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: thought_chars >= 1
  - constraint: thought_chars <= (select max_thought_chars from workspaces where workspaces.id = thought_logs.workspace_id)
- `usage_daily.json` — Pre-aggregated per-day usage counters to enforce quotas for think calls and total characters. (17 rows; fields: ['id', 'workspace_id', 'api_key_id', 'usage_date', 'think_calls', 'thought_chars', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'finalized']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(workspace_id, api_key_id, usage_date)
  - constraint: think_calls >= 0

## Business rules enforced by the tools

- Calling the think tool MUST create exactly one thought_logs row with thought_logs.thought equal to the tool parameter `thought` and status='recorded', unless the request is rejected for auth/quota/validation.
- The think tool MUST reject requests where `thought` is empty or only whitespace after trimming.
- The think tool MUST reject requests where length(thought) exceeds workspaces.max_thought_chars for the authenticated workspace.
- Authentication MUST map the presented credential to exactly one api_keys row with status='active' and a workspace whose status='active'.
- If a client_request_id is provided by middleware, the server MUST enforce idempotency within a workspace: repeated requests with the same (workspace_id, client_request_id) MUST NOT create additional thought_logs rows.
- On each successful think call, usage_daily counters MUST be incremented atomically for: (workspace_id, api_key_id, usage_date) and (workspace_id, null, usage_date).
- The server MUST reject a think call that would cause (workspace daily think_calls) to exceed workspaces.daily_thought_limit or (workspace daily thought_chars) to exceed workspaces.daily_char_limit.
- Thought logs are append-only by default: updates are only allowed as status transitions recorded->redacted->deleted, and redaction MUST replace thought with a constant placeholder while retaining thought_sha256 and thought_chars for audit consistency.
- Deleting a workspace is a soft-delete (status='deleted'); API keys in deleted workspaces MUST be treated as unauthorized, and no new thought_logs rows may be created for deleted/suspended workspaces.