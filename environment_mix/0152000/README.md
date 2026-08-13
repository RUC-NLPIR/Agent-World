# Think Tool — local MCP environment

This backend stores per-session "thought logs" appended by the think tool, and supports reading, clearing, and basic statistics for the current session. The core workflow is: a client/session is created, thoughts are appended in order, stats are computed over the session’s thoughts, and the session can be cleared (soft-cleared or hard-deleted) to reset the log.

Repository: https://github.com/iamwavecut/MCP-Think
Homepage: https://smithery.ai/server/@iamwavecut/mcp-think

## Datastore

- `sessions.json` — Represents an isolated "current session" context for recording and retrieving thoughts. A session is the unit of isolation for clear/get/stats operations. (18 rows; fields: ['id', 'client_key', 'status', 'cleared_at', 'thought_count', 'total_chars', 'last_thought_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'cleared', 'archived']
  - constraint: unique(client_key) WHERE client_key IS NOT NULL AND status IN ('active','cleared')
  - constraint: thought_count >= 0
  - constraint: total_chars >= 0
- `thoughts.json` — Immutable(ish) append-only thought entries recorded for a session, in sequence order. Used by get_thoughts and get_thought_stats; clear_thoughts marks them deleted and updates session counters. (18 rows; fields: ['id', 'session_id', 'sequence', 'thought', 'thought_chars', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'deleted']
  - constraint: foreign key(session_id) references sessions(id) on delete cascade
  - constraint: unique(session_id, sequence)
  - constraint: sequence >= 1
  - constraint: length(thought) >= 1
- `session_resets.json` — Audit log of clear operations for a session. Allows computing operational stats and supports idempotency/diagnostics even if thoughts are soft-deleted. (18 rows; fields: ['id', 'session_id', 'status', 'cleared_thoughts_count', 'cleared_total_chars', 'created_at', 'updated_at'])
  - lifecycle `status`: ['applied', 'rolled_back']
  - constraint: foreign key(session_id) references sessions(id) on delete cascade
  - constraint: cleared_thoughts_count >= 0
  - constraint: cleared_total_chars >= 0
- `api_keys.json` — Optional authentication/tenant mechanism for callers. Not explicit in the tool surface, but typical for an API service and used to scope the 'current session' and enforce quotas. (17 rows; fields: ['id', 'key_hash', 'name', 'status', 'rate_limit_rpm', 'max_thought_chars', 'max_session_thoughts', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_rpm between 1 and 6000
  - constraint: max_thought_chars between 1 and 200000
  - constraint: max_session_thoughts between 1 and 100000
- `request_log.json` — Operational log for tool calls to support debugging, metering, and rate limiting. Each tool call is recorded with session association and outcome. (18 rows; fields: ['id', 'api_key_id', 'session_id', 'tool_name', 'status', 'request_payload', 'response_meta', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['success', 'error', 'rate_limited']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: foreign key(session_id) references sessions(id) on delete set null
  - constraint: duration_ms >= 0 and duration_ms <= 600000

## Business rules enforced by the tools

- Tool think(thought) MUST create a sessions row in status=active if no current session exists for the caller context; then insert a thoughts row with status=recorded, sequence = (max(sequence) in session)+1, thought_chars=length(thought), and update sessions.thought_count/total_chars/last_thought_at atomically.
- Tool think(thought) MUST reject empty thought strings and MUST enforce max_thought_chars from api_keys when api_key_id is present; otherwise enforce a server default of 200000 characters.
- Tool get_thoughts MUST return thoughts for the current session ordered by sequence ascending and MUST exclude thoughts where status='deleted'.
- Tool get_thought_stats MUST compute at minimum: count of non-deleted thoughts, total_chars of non-deleted thoughts, and last_thought_at; it MAY serve these from cached sessions fields but MUST be consistent with thoughts table after successful writes/clears.
- Tool clear_thoughts MUST soft-delete all thoughts in the current session by setting status='deleted' and deleted_at, create a session_resets row with cleared counts/chars, and set sessions.status='cleared', sessions.thought_count=0, sessions.total_chars=0, sessions.last_thought_at=NULL in a single transaction.
- After clear_thoughts, a subsequent think MUST transition sessions.status from cleared -> active and continue sequence numbering monotonically (do not reuse sequence numbers) OR create a new session; whichever strategy is chosen, it must be consistent across get_thoughts/get_thought_stats (this model supports monotonic sequences within a single session).
- Rate limiting MUST be enforced per api_keys.rate_limit_rpm using request_log timestamps; requests beyond limit MUST be recorded with request_log.status='rate_limited' and must not mutate thoughts/sessions.
- sessions.client_key, when used, MUST map to at most one non-archived session at a time; creating a new session for the same client_key MUST archive the previous one or reuse it.
- FK integrity: deleting a session MUST cascade-delete thoughts and session_resets; deleting an api_key MUST not delete historical request_log rows but set request_log.api_key_id to NULL.
- Statuses MUST respect declared transitions; e.g., thoughts cannot move from deleted back to recorded, and api_keys cannot be un-revoked.