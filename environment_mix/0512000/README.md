# Python Local Server — local MCP environment

This backend stores stateful Python REPL sessions and their execution history, enabling code to be run incrementally while preserving variables across calls. The main workflow is: a client supplies a session_id and code, the server executes it within the session context, records the run, and returns a summarized result while retaining full stdout/stderr for audit/debug.

Repository: https://github.com/Alec2435/python_mcp
Homepage: https://smithery.ai/server/@Alec2435/python_mcp

## Datastore

- `repl_sessions.json` — Stateful Python REPL sessions keyed by a client-provided session_id. Holds lifecycle status and metadata needed to maintain and govern session execution. (18 rows; fields: ['id', 'session_id', 'status', 'python_version', 'last_activity_at', 'closed_at', 'close_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'idle', 'closed', 'error']
  - constraint: unique(session_id)
  - constraint: session_id length between 1 and 128
  - constraint: closed_at is null unless status = 'closed'
  - constraint: status = 'error' implies last_activity_at is not null
- `repl_executions.json` — One row per python_repl invocation (code execution) within a session, including code, timing, outcome, and pointers to captured outputs. (19 rows; fields: ['id', 'session_id', 'sequence_no', 'status', 'code', 'started_at', 'finished_at', 'duration_ms', 'result_summary', 'exception_type', 'exception_message', 'traceback_text', 'stdout_bytes', 'stderr_bytes', 'output_capture_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(session_id) references repl_sessions(id) on delete cascade
  - constraint: unique(session_id, sequence_no)
  - constraint: sequence_no >= 1
  - constraint: stdout_bytes >= 0
- `repl_outputs.json` — Stores full captured stdout/stderr and any structured return value metadata for an execution. Kept separate to allow truncation/policy management and cheaper queries on execution history. (19 rows; fields: ['id', 'execution_id', 'stdout_text', 'stderr_text', 'return_repr', 'mime_bundle', 'truncated', 'max_bytes_applied', 'created_at', 'updated_at'])
  - lifecycle `truncated`: [False, True]
  - constraint: foreign key(execution_id) references repl_executions(id) on delete cascade
  - constraint: unique(execution_id)
  - constraint: max_bytes_applied is null unless truncated = true
  - constraint: max_bytes_applied >= 0 when not null
- `repl_session_variables.json` — Optional persisted view of session variables/metadata for governance and debugging. Stores only lightweight, safe-to-persist summaries (not full Python objects). (19 rows; fields: ['id', 'session_id', 'name', 'type_name', 'repr_preview', 'estimated_size_bytes', 'last_seen_execution_id', 'created_at', 'updated_at'])
  - lifecycle `name`: []
  - constraint: foreign key(session_id) references repl_sessions(id) on delete cascade
  - constraint: foreign key(last_seen_execution_id) references repl_executions(id) on delete set null
  - constraint: unique(session_id, name)
  - constraint: estimated_size_bytes is null or estimated_size_bytes >= 0

## Business rules enforced by the tools

- python_repl(code, session_id) must resolve session_id to repl_sessions.session_id; if no row exists, create a new repl_sessions row with status='active' and set python_version from the runtime.
- A python_repl call must create exactly one repl_executions row with code exactly equal to the provided parameter and linked to the session via repl_sessions.id.
- repl_executions.sequence_no must increment by 1 per session; concurrent requests for the same session must be serialized or use a transactional increment to preserve unique(session_id, sequence_no).
- A session in status='closed' must reject new executions; attempts must not create repl_executions rows.
- Execution status must follow allowed transitions; once in succeeded/failed/cancelled it is immutable.
- For each execution that reaches succeeded/failed/cancelled, started_at and finished_at must be set and duration_ms must equal finished_at-started_at in milliseconds (rounded consistently).
- If execution fails, exception_type must be set and traceback_text should be persisted (possibly truncated) and associated output_capture_id should reference a repl_outputs row when any output exists.
- Captured stdout/stderr must be stored in repl_outputs when non-empty or when configured to always capture; repl_executions.stdout_bytes/stderr_bytes must match the stored payload sizes (post-truncation).
- Output truncation limits must be enforced: if stored stdout/stderr exceed max_bytes_applied, repl_outputs.truncated must be true and only the truncated content may be stored.
- repl_sessions.last_activity_at must be updated on every execution start or completion; if no activity occurs for a configured TTL, the system may transition status from active/idle to closed with close_reason='timeout'.
- If repl_session_variables is enabled, after each successful execution the system may upsert variable summaries, but it must not persist raw unserializable objects; repr_preview must be truncated to a configured max length.