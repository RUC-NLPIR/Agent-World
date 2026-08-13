# Remote Shell Server — local MCP environment

This backend stores authenticated clients, their allowed execution policies, and an audit log of all remote shell command executions. The main workflow is: a client presents an API key, the server validates policy/quota, executes a command in a sandboxed context, then persists the request, output metadata, and status for auditing and rate-limiting.

Repository: https://github.com/samihalawa/remote-shell-terminal-mcp
Homepage: https://smithery.ai/server/@samihalawa/remote-shell-terminal-mcp

## Datastore

- `workspaces.json` — Tenant container for API keys, policies, and execution logs. (12 rows; fields: ['id', 'name', 'status', 'default_timeout_ms', 'max_timeout_ms', 'max_command_length', 'allowed_cwd_roots', 'deny_command_regexes', 'allow_command_regexes', 'rate_limit_per_minute', 'daily_exec_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_timeout_ms >= 1
  - constraint: max_timeout_ms >= default_timeout_ms
  - constraint: max_timeout_ms <= 300000
- `api_keys.json` — API keys used to authenticate access to shell execution. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'key_prefix', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, workspace_id)
- `execution_sessions.json` — Execution context metadata for a remote shell command run (cwd, timeout, environment policy). (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'requested_cwd', 'effective_cwd', 'requested_timeout_ms', 'effective_timeout_ms', 'client_ip', 'user_agent', 'status', 'rejection_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'running', 'completed', 'failed', 'timed_out', 'rejected']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: effective_timeout_ms >= 1
  - constraint: effective_timeout_ms <= 300000
- `command_executions.json` — Immutable audit log row for each shell-exec call, including command, outputs and execution result metadata. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'session_id', 'command', 'command_sha256', 'status', 'exit_code', 'stdout', 'stderr', 'output_truncated', 'max_output_bytes', 'started_at', 'finished_at', 'duration_ms', 'rejection_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'rejected']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: foreign key (session_id) references execution_sessions(id) on delete restrict
  - constraint: length(command) >= 1
- `usage_counters.json` — Pre-aggregated usage for enforcing per-minute and daily execution quotas. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'window_type', 'window_start', 'exec_count', 'rejected_count', 'timed_out_count', 'created_at', 'updated_at'])
  - constraint: foreign key (workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key (api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(workspace_id, api_key_id, window_type, window_start)
  - constraint: exec_count >= 0

## Business rules enforced by the tools

- shell-exec must create exactly one execution_sessions row and one command_executions row per request; command_executions.session_id must reference that session.
- The tool parameter 'command' maps to command_executions.command and must be non-empty and length <= workspaces.max_command_length for the authenticated workspace.
- The tool parameter 'cwd' maps to execution_sessions.requested_cwd; if provided, execution_sessions.effective_cwd must be a normalized absolute path and must start with one of workspaces.allowed_cwd_roots (when allowed_cwd_roots is non-empty). Otherwise the request must be rejected (status=rejected) with a rejection_reason.
- The tool parameter 'timeout' (ms) maps to execution_sessions.requested_timeout_ms; effective_timeout_ms must equal min(max(requested_timeout_ms, 1), workspaces.max_timeout_ms). If timeout is omitted, effective_timeout_ms must equal workspaces.default_timeout_ms.
- Before executing, the service must enforce policy: if workspaces.allow_command_regexes is non-empty then command must match at least one; command must match none of workspaces.deny_command_regexes; otherwise the request must be rejected and logged (command_executions.status=rejected).
- Rate limiting: for each accepted request, increment usage_counters for window_type=minute (workspace aggregate) and enforce usage_counters.exec_count < workspaces.rate_limit_per_minute; if exceeded, reject and increment rejected_count.
- Daily quota: if workspaces.daily_exec_limit is not null, enforce workspace daily exec_count < daily_exec_limit; if exceeded, reject and increment rejected_count.
- On completion, command_executions.status must transition from running to succeeded/failed/timed_out and set finished_at and duration_ms; exit_code must be set for succeeded/failed and must be null for rejected.
- Output size must be capped: stdout/stderr may be truncated to max_output_bytes; if truncated, output_truncated=true.
- Workspace status must be active to accept executions; suspended/deleted workspaces must cause immediate rejection and logging.
- API keys must be active to execute; revoked keys must cause immediate rejection and logging.
- FK integrity must be enforced: a command_executions row cannot exist without valid workspace_id, api_key_id, and session_id.