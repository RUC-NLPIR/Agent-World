# Sequential Thinking — local MCP environment

This backend stores multi-step "thinking sessions" where a client submits sequential thoughts, optionally revising prior thoughts and branching into alternative lines of reasoning. The main workflow is: a client (scoped by API key) creates/continues a session by appending thought events, which can reference earlier thoughts for revisions and branch lineage, and the session is marked complete when no more thoughts are needed.

Repository: https://github.com/kiennd/reference-servers
Homepage: https://smithery.ai/server/@kiennd/reference-servers

## Datastore

- `api_keys.json` — API keys used to authenticate callers and apply basic quotas for sequential thinking sessions and thought events. (18 rows; fields: ['id', 'key_hash', 'label', 'status', 'requests_per_minute_limit', 'max_active_sessions', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit >= 1 AND requests_per_minute_limit <= 6000
  - constraint: max_active_sessions >= 1 AND max_active_sessions <= 100000
  - constraint: revoked_at IS NULL OR status = 'revoked'
- `thinking_sessions.json` — A session groups a sequence of thought events, including revisions and branches, for a single problem-solving run by a caller. (17 rows; fields: ['id', 'api_key_id', 'status', 'current_branch_id', 'last_thought_number', 'estimated_total_thoughts', 'completed_at', 'cancelled_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'cancelled']
  - constraint: foreign key(api_key_id) references api_keys(id)
  - constraint: last_thought_number >= 0
  - constraint: estimated_total_thoughts >= 1
  - constraint: completed_at IS NULL OR status = 'completed'
- `thought_events.json` — Append-only thought steps submitted to the sequentialthinking tool, including revision and branching metadata. Each call to the tool creates one thought event. (18 rows; fields: ['id', 'session_id', 'status', 'thought', 'next_thought_needed', 'needs_more_thoughts', 'thought_number', 'total_thoughts', 'is_revision', 'revises_thought_number', 'branch_from_thought_number', 'branch_id', 'rejection_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['accepted', 'rejected']
  - constraint: foreign key(session_id) references thinking_sessions(id)
  - constraint: thought_number >= 1
  - constraint: total_thoughts >= 1
  - constraint: branch_from_thought_number IS NULL OR branch_from_thought_number >= 1
- `branches.json` — Tracks branch identifiers within a session and their lineage, allowing the system to validate branchFromThought and group thoughts by branchId. (18 rows; fields: ['id', 'session_id', 'branch_id', 'status', 'parent_branch_id', 'branched_from_thought_number', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closed']
  - constraint: foreign key(session_id) references thinking_sessions(id)
  - constraint: unique(session_id, branch_id)
  - constraint: branched_from_thought_number IS NULL OR branched_from_thought_number >= 1
- `request_logs.json` — Immutable request/response metadata for the sequentialthinking tool call for auditability, debugging, and rate-limit enforcement. (18 rows; fields: ['id', 'api_key_id', 'session_id', 'thought_event_id', 'tool_name', 'input', 'response', 'http_status', 'latency_ms', 'created_at', 'updated_at'])
  - constraint: foreign key(api_key_id) references api_keys(id)
  - constraint: foreign key(session_id) references thinking_sessions(id)
  - constraint: foreign key(thought_event_id) references thought_events(id)
  - constraint: http_status >= 100 AND http_status <= 599

## Business rules enforced by the tools

- Each call to tool_name='sequentialthinking' must create exactly one request_logs row with input containing required fields: thought, nextThoughtNeeded, thoughtNumber, totalThoughts.
- A thought_events row must be created per call; it is status='accepted' only if the owning session status is 'active' at the time of processing; otherwise it must be status='rejected' with rejection_reason set.
- thought_events.thought_number must be >= 1 and total_thoughts must be >= 1; values outside schema minimums must be rejected.
- If thought_events.is_revision is true, then revises_thought_number must be provided and must refer to an existing accepted thought_events.thought_number within the same session (and same branch_id if branch_id is set).
- If thought_events.branch_id is provided and does not exist in branches for the session, the system must create a branches row; if branch_from_thought_number is provided, the new branch must record branched_from_thought_number and parent_branch_id (if determinable) and the referenced thought number must exist as an accepted thought in the session.
- Within a given (session_id, branch_id) pair, thought_number must be unique; attempts to reuse a thought_number must be rejected.
- thinking_sessions.estimated_total_thoughts must be updated to the latest accepted thought_events.total_thoughts (or max of seen values, depending on implementation), and last_thought_number must be updated to the maximum accepted thought_number observed for the current branch or overall session (implementation-defined but consistent).
- If a call has nextThoughtNeeded=false OR needsMoreThoughts=false (when provided), the server must transition the session from active to completed and set completed_at, unless the session is already completed/cancelled.
- api_keys.status='revoked' must cause all requests to be rejected (http_status 401/403) and no sessions may be created; a request_logs record must still be written for auditing.
- Enforce per-key requests_per_minute_limit by counting request_logs for the api_key_id over a rolling 60-second window; over-limit requests must be rejected (http_status 429).
- Enforce max_active_sessions by counting thinking_sessions for api_key_id where status='active'; if the limit would be exceeded by creating a new session, the request must be rejected.
- Status transitions must follow the declared lifecycle transitions; direct writes that violate transitions must be prevented.