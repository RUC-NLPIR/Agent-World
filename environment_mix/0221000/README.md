# iTerm MCP — local MCP environment

This backend stores sessions and interaction history for an MCP server that controls iTerm: writing input, reading output, and sending control characters to the active terminal. The primary workflow is: an MCP client authenticates, attaches to (or creates) a session bound to the currently active iTerm terminal, then issues commands that are persisted as events and terminal output snapshots for later reads and auditing.

Repository: https://github.com/lite/iterm-mcp
Homepage: https://smithery.ai/server/@lite/iterm-mcp

## Datastore

- `api_keys.json` — API keys used by MCP clients to authenticate to the iTerm MCP server and to apply per-key quotas and auditing. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'scopes', 'rate_limit_per_minute', 'burst_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute >= 1
  - constraint: burst_limit >= 0
  - constraint: status in ('active','revoked')
- `terminal_sessions.json` — Server-side sessions bound to the currently active iTerm terminal context; used to group terminal events and output reads for auditing and consistent reads. (26 rows; fields: ['id', 'api_key_id', 'status', 'active_terminal_fingerprint', 'last_activity_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'ended', 'expired']
  - constraint: fk(api_key_id) references api_keys(id)
  - constraint: status in ('active','ended','expired')
  - constraint: expires_at is null OR expires_at > created_at
- `terminal_events.json` — Immutable audit log of all tool invocations against iTerm, including writes, reads, and control character sends, with timing and outcome. (32 rows; fields: ['id', 'session_id', 'api_key_id', 'tool_name', 'status', 'request_payload', 'error_message', 'duration_ms', 'terminal_fingerprint', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: fk(session_id) references terminal_sessions(id)
  - constraint: fk(api_key_id) references api_keys(id)
  - constraint: tool_name in ('write_to_terminal','read_terminal_output','send_control_character')
  - constraint: status in ('succeeded','failed')
- `terminal_output_snapshots.json` — Captured outputs read from the active iTerm terminal, stored as snapshots and linked to the read events that produced them. (32 rows; fields: ['id', 'event_id', 'session_id', 'status', 'output_text', 'output_bytes', 'content_encoding', 'started_at', 'ended_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['stored', 'redacted', 'expired']
  - constraint: fk(event_id) references terminal_events(id)
  - constraint: fk(session_id) references terminal_sessions(id)
  - constraint: unique(event_id)
  - constraint: output_bytes >= 0
- `usage_counters.json` — Per-API-key rolling usage and quota enforcement materialization for tool calls (supports server-side rate limiting and simple billing/limits). (32 rows; fields: ['id', 'api_key_id', 'window_start_at', 'window_seconds', 'tool_name', 'call_count', 'error_count', 'created_at', 'updated_at'])
  - constraint: fk(api_key_id) references api_keys(id)
  - constraint: unique(api_key_id, window_start_at, window_seconds, tool_name)
  - constraint: window_seconds in (60, 300, 3600)
  - constraint: call_count >= 0

## Business rules enforced by the tools

- Every tool invocation (write_to_terminal, read_terminal_output, send_control_character) MUST create exactly one terminal_events row with tool_name set accordingly and request_payload = {} (empty object) given the current tool schemas.
- read_terminal_output MUST create exactly one terminal_output_snapshots row linked by terminal_output_snapshots.event_id to the terminal_events.id of that invocation when the read succeeds; if the read fails, no snapshot row is created.
- A terminal_output_snapshots row MUST have unique(event_id) to guarantee one snapshot per read invocation.
- Tool calls MUST be rejected if api_keys.status != 'active' or if the api key scopes array does not contain the requested tool name.
- Tool calls MUST be rejected if the associated terminal_session.status != 'active' or if expires_at is not null and now() >= expires_at; if expired, the server MUST transition the session status to 'expired'.
- Rate limiting: for each tool call, the server MUST upsert the corresponding usage_counters bucket and MUST reject the call if the resulting call_count would exceed api_keys.rate_limit_per_minute (and/or burst_limit if implemented as a token bucket).
- For auditing integrity, terminal_events rows are append-only: tool_name and created_at MUST NOT change after insert; only updated_at, duration_ms, status, and error_message may be updated to finalize an in-flight write.
- terminal_output_snapshots.output_text MUST be nulled when status transitions to 'redacted' or 'expired', and output_bytes MUST remain as originally recorded for accounting/audit.
- Foreign key integrity MUST be enforced: terminal_events.session_id must reference an existing terminal_sessions row; terminal_sessions.api_key_id and terminal_events.api_key_id must reference an existing api_keys row.