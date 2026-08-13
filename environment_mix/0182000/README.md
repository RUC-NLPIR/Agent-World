# Think MCP Server — local MCP environment

This backend stores append-only "thought" logs produced by clients calling the Think MCP Server. The primary workflow is: authenticate a client (optionally by API key), accept a thought string via the think tool, persist it as an immutable log entry, and track basic rate/usage for abuse prevention and auditing.

Repository: https://github.com/marcopesani/think-mcp-server
Homepage: https://smithery.ai/server/@marcopesani/think-mcp-server

## Datastore

- `workspaces.json` — Tenant container for thoughts and API access controls. A workspace may represent a single user, team, or integration environment. (12 rows; fields: ['id', 'slug', 'display_name', 'status', 'thought_retention_days', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: display_name <> ''
  - constraint: thought_retention_days >= 0
  - constraint: cannot_update_when(status='deleted')
- `api_keys.json` — API keys used to authenticate calls and attribute thought logs to a caller. Stores only a hash of the secret. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'secret_hash', 'status', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: foreign_key(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_prefix)
  - constraint: key_prefix <> ''
- `thought_logs.json` — Append-only log of thoughts submitted via the think tool. This is the core entity the service persists. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'thought', 'thought_sha256', 'status', 'redacted_reason', 'client_request_id', 'ip_address', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['accepted', 'redacted', 'deleted']
  - constraint: foreign_key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign_key(api_key_id) references api_keys(id) on delete set null
  - constraint: thought <> ''
  - constraint: length(thought) <= 20000
- `usage_counters.json` — Pre-aggregated usage accounting for quotas and abuse prevention (e.g., per workspace per day). (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'window_start', 'window_end', 'thought_count', 'char_count', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'finalized', 'recomputed']
  - constraint: foreign_key(workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign_key(api_key_id) references api_keys(id) on delete set null
  - constraint: window_end > window_start
  - constraint: thought_count >= 0

## Business rules enforced by the tools

- The think tool must create exactly one thought_logs row per successful call, mapping parameters.thought -> thought_logs.thought and computing thought_sha256 from the exact received string.
- The think tool must not modify any existing domain data except: (a) updating api_keys.last_used_at for the authenticating key, and (b) incrementing/creating usage_counters for the appropriate counting window.
- thought_logs inserts are rejected if the associated workspace.status is not 'active'.
- If an API key is provided, authentication must ensure api_keys.status='active' and (api_keys.expires_at is null OR api_keys.expires_at > now()). Calls with revoked/expired keys are rejected and must not write thought_logs.
- Idempotency: if client_request_id is provided and a thought_logs row already exists with the same (workspace_id, client_request_id), the server must not create a second row and should return the existing entry's id.
- Quota enforcement: for each workspace, accepted think calls per UTC day must be <= 10000 and total accepted characters per UTC day must be <= 50,000,000; exceeding either limit rejects the call.
- Thought payload validation: thought must be non-empty and length(thought) <= 20000 characters; otherwise reject without writing.
- Retention: a background job may delete or mark deleted thought_logs older than workspaces.thought_retention_days (unless retention_days=0), but only via allowed lifecycle transitions accepted/redacted -> deleted.