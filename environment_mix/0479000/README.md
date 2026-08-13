# Think Tool Server — local MCP environment

This backend stores per-session "thought" log entries appended by the think tool, plus session-level metadata for basic lifecycle and statistics. Core workflows: append a thought to the active session, list thoughts for a session, clear thoughts for a session (soft-delete), and compute session stats (counts/lengths/timestamps).

Repository: https://github.com/cgize/claude-mcp-think-tool
Homepage: https://smithery.ai/server/@cgize/claude-mcp-think-tool

## Datastore

- `sessions.json` — Represents a single client/tool session that owns an ordered log of thoughts and supports lifecycle (active/closed). Used as the scope for get_thoughts, clear_thoughts, and get_thought_stats. (12 rows; fields: ['id', 'status', 'last_activity_at', 'closed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closed']
  - constraint: status IN ('active','closed')
  - constraint: closed_at IS NULL OR status = 'closed'
  - constraint: last_activity_at >= created_at
- `thoughts.json` — Append-only (log) thought entries within a session. Clearing thoughts is represented as soft-deleting all thoughts in the session. (16 rows; fields: ['id', 'session_id', 'seq', 'thought', 'thought_sha256', 'char_count', 'status', 'cleared_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'cleared']
  - constraint: FK(session_id) REFERENCES sessions(id) ON DELETE CASCADE
  - constraint: unique(session_id, seq)
  - constraint: char_count >= 0
  - constraint: length(thought) > 0
- `session_counters.json` — Per-session derived counters maintained transactionally to make get_thought_stats fast and consistent (counts, lengths, last timestamps). (12 rows; fields: ['session_id', 'total_thoughts', 'total_chars', 'max_seq', 'first_thought_at', 'last_thought_at', 'last_cleared_at', 'created_at', 'updated_at'])
  - lifecycle `session_id`: ['(implicit)']
  - constraint: FK(session_id) REFERENCES sessions(id) ON DELETE CASCADE
  - constraint: total_thoughts >= 0
  - constraint: total_chars >= 0
  - constraint: max_seq >= 0
- `session_events.json` — Immutable audit/event stream for session actions (append thought, clear thoughts). Supports debugging, replay, and compliance without relying on mutable rows alone. (19 rows; fields: ['id', 'session_id', 'event_type', 'thought_id', 'payload', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['thought_appended', 'thoughts_cleared', 'session_closed']
  - constraint: FK(session_id) REFERENCES sessions(id) ON DELETE CASCADE
  - constraint: FK(thought_id) REFERENCES thoughts(id) ON DELETE SET NULL
  - constraint: event_type IN ('thought_appended','thoughts_cleared','session_closed')
  - constraint: thought_id IS NOT NULL WHEN event_type = 'thought_appended'

## Business rules enforced by the tools

- Tool scope is per-session: think/get_thoughts/clear_thoughts/get_thought_stats MUST operate only on the current session_id resolved by the runtime (not user-provided).
- think(thought) MUST insert a thoughts row with status='recorded', compute thought_sha256 and char_count, and allocate seq = session_counters.max_seq + 1 in a single transaction to guarantee unique(session_id, seq).
- think(thought) MUST reject empty strings and MUST enforce a maximum length (e.g., length(thought) <= 20000) to prevent unbounded storage growth.
- get_thoughts MUST return thoughts for the session ordered by seq ascending and MUST exclude rows with status='cleared'.
- clear_thoughts MUST mark all recorded thoughts in the session as status='cleared' and set cleared_at for each, and MUST emit exactly one session_events row with event_type='thoughts_cleared' including payload.cleared_count.
- After clear_thoughts, session_counters.total_thoughts MUST be 0, total_chars MUST be 0, first_thought_at and last_thought_at MUST be NULL, and last_cleared_at MUST be set.
- get_thought_stats MUST be computed from session_counters (or an equivalent consistent snapshot) and include at minimum: total_thoughts, total_chars, first_thought_at, last_thought_at, last_cleared_at.
- Sessions with status='closed' MUST reject think and clear_thoughts; get_thoughts and get_thought_stats MAY be allowed read-only.
- All writes (think, clear_thoughts) MUST update sessions.last_activity_at and sessions.updated_at, and MUST append a corresponding session_events record for observability.
- Foreign key integrity MUST be enforced: thoughts.session_id and session_events.session_id must reference an existing sessions row; deleting a session MUST cascade-delete its thoughts, counters, and events.