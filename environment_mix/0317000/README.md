# Terminal MCP Server — local MCP environment

This backend stores authenticated clients, their terminal execution sessions (local or SSH), and an auditable log of every command executed along with outputs and exit status. The main workflow is: an API client calls execute_command, the service resolves (or creates) a session scoped by client+host+username+session name, runs the command with provided env vars, stores the execution record/output, and reuses the session for up to 20 minutes of inactivity.

Repository: https://github.com/weidwonder/terminal-mcp-server
Homepage: https://smithery.ai/server/@weidwonder/terminal-mcp-server

## Datastore

- `api_keys.json` — API keys used to authenticate callers of the MCP server. Keys own sessions and command executions and are the unit for quotas and auditing. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: key_prefix length between 4 and 16
- `hosts.json` — Known execution targets. A row represents either the local machine target or a remote SSH host target. Remote hosts are keyed by hostname/ip and username to support different accounts on the same host. (12 rows; fields: ['id', 'type', 'host', 'username', 'port', 'fingerprint', 'created_at', 'updated_at'])
  - constraint: check(type in ('local','ssh'))
  - constraint: check((type='local' and host is null and username is null and port=0) or (type='ssh' and host is not null and username is not null and port between 1 and 65535))
  - constraint: unique(type, host, username, port)
- `terminal_sessions.json` — Reusable terminal environments keyed by (api_key, host, session_name). Sessions are kept alive for up to 20 minutes of inactivity and allow environment continuity (e.g., activated conda env). (18 rows; fields: ['id', 'api_key_id', 'host_id', 'session_name', 'status', 'created_at', 'updated_at', 'last_used_at', 'expires_at', 'connection_ref', 'last_error'])
  - lifecycle `status`: ['active', 'expired', 'closed', 'error']
  - constraint: unique(api_key_id, host_id, session_name) where status in ('active','error')
  - constraint: check(length(session_name) between 1 and 64)
  - constraint: check(expires_at >= last_used_at)
  - constraint: foreign key(api_key_id) references api_keys(id) on delete cascade
- `command_executions.json` — Immutable audit log of each execute_command call: input parameters, resolved session/host, captured stdout/stderr, and exit status. Supports debugging, compliance, and rate limiting. (19 rows; fields: ['id', 'api_key_id', 'host_id', 'terminal_session_id', 'request_session_name', 'request_host', 'request_username', 'command', 'env', 'status', 'exit_code', 'stdout', 'stderr', 'output_truncated', 'duration_ms', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: foreign key(host_id) references hosts(id) on delete restrict
  - constraint: foreign key(terminal_session_id) references terminal_sessions(id) on delete set null
  - constraint: check(length(command) between 1 and 32768)
- `usage_quotas.json` — Per-API-key throttling and safety limits to prevent abuse (command rate, concurrency, and output size). Enforced at request time and updated as executions are recorded. (12 rows; fields: ['id', 'api_key_id', 'status', 'max_concurrent_executions', 'max_executions_per_minute', 'max_command_length', 'max_env_bytes', 'max_output_bytes', 'execution_timeout_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['enabled', 'disabled']
  - constraint: unique(api_key_id)
  - constraint: foreign key(api_key_id) references api_keys(id) on delete cascade
  - constraint: check(max_concurrent_executions between 1 and 100)
  - constraint: check(max_executions_per_minute between 1 and 6000)

## Business rules enforced by the tools

- execute_command must require command and reject empty/whitespace-only command.
- If execute_command.host is provided then execute_command.username must be provided; otherwise the request is rejected.
- If host is omitted, the execution target must resolve to a single hosts row with type='local' (created if missing).
- If host is provided, the execution target must resolve to hosts(type='ssh', host, username, port=22 unless configured otherwise); create if missing.
- The resolved terminal session is identified by (api_key_id, host_id, session_name). If an active session exists with expires_at > now(), reuse it; otherwise create a new session with status='active' and expires_at=now()+20 minutes.
- On every accepted execute_command call, a command_executions row must be created with status='queued' (or 'running' if executed synchronously) and must persist request_session_name, request_host, request_username, command, and env exactly as received (subject to redaction policy if implemented).
- When an execution starts, command_executions.status must transition to 'running' and started_at must be set; when it ends, status must be one of succeeded/failed/timed_out/cancelled and finished_at and duration_ms must be set.
- exit_code must be set only when status is succeeded or failed; exit_code must be null for cancelled and may be null for timed_out depending on runtime behavior.
- terminal_sessions.last_used_at must be updated to now() and expires_at recalculated to now()+20 minutes whenever an execution uses that session, regardless of success/failure.
- If api_keys.status != 'active', execute_command must be rejected and no command_executions row may be created.
- If usage_quotas.status='enabled', then before accepting execute_command the service must enforce: (a) running executions for the api_key_id < max_concurrent_executions, (b) accepted executions in the last 60 seconds < max_executions_per_minute, (c) length(command) <= max_command_length, (d) serialized env size <= max_env_bytes.
- Captured output must be truncated to max_output_bytes when quota is enabled; command_executions.output_truncated must reflect whether truncation occurred.
- When a session is unused past expires_at, it must transition from active to expired, and underlying runtime resources referenced by connection_ref must be released; expired sessions may transition to closed but never back to active.