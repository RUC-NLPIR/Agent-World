# Browserbase — local MCP environment

This backend stores cloud browser sessions (single and multi), along with the ordered interaction steps performed via Stagehand (navigate/act/observe/extract) and artifacts such as screenshots. Primary workflows are: create/reuse a session, run step operations against the session, capture outputs (observations, extractions, screenshots), list/close multi-sessions, and close the active single-session.

Repository: https://github.com/browserbase/mcp-server-browserbase
Homepage: https://smithery.ai/server/@browserbasehq/mcp-browserbase

## Datastore

- `workspaces.json` — Tenant container for Browserbase usage. Used to scope sessions and enforce quota/billing limits. (12 rows; fields: ['id', 'name', 'status', 'plan', 'session_concurrency_limit', 'monthly_session_minutes_limit', 'monthly_session_minutes_used', 'monthly_step_limit', 'monthly_step_used', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: session_concurrency_limit >= 1
  - constraint: monthly_session_minutes_limit >= 0
  - constraint: monthly_session_minutes_used >= 0
- `stagehand_sessions.json` — Represents a Browserbase cloud browser session with Stagehand initialized. Supports both the single-session tools (one 'active' per workspace) and multi-session tools (many). (31 rows; fields: ['id', 'workspace_id', 'mode', 'name', 'browserbase_session_id', 'status', 'current_url', 'started_at', 'closed_at', 'last_activity_at', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['initializing', 'running', 'paused', 'closing', 'closed', 'failed']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: mode in ('single','multi')
  - constraint: status in ('initializing','running','paused','closing','closed','failed')
  - constraint: browserbase_session_id is unique when not null
- `session_steps.json` — Immutable log of all Stagehand operations (navigate/act/observe/extract/screenshot) executed against a session, storing inputs and outputs for debugging and reproducibility. (35 rows; fields: ['id', 'session_id', 'sequence', 'type', 'status', 'input_url', 'input_action', 'input_variables', 'input_instruction', 'input_return_action', 'input_screenshot_name', 'output', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(session_id) references stagehand_sessions(id) on delete cascade
  - constraint: unique(session_id, sequence)
  - constraint: sequence >= 1
  - constraint: type in ('navigate','act','observe','extract','screenshot')
- `artifacts.json` — Binary/large artifacts produced by sessions (primarily screenshots). Stores metadata and storage pointers. (37 rows; fields: ['id', 'session_id', 'step_id', 'type', 'name', 'content_type', 'byte_size', 'storage_provider', 'storage_key', 'sha256', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'available', 'deleted', 'failed']
  - constraint: fk(session_id) references stagehand_sessions(id) on delete cascade
  - constraint: fk(step_id) references session_steps(id) on delete set null
  - constraint: byte_size >= 0
  - constraint: content_type <> ''

## Business rules enforced by the tools

- multi_browserbase_stagehand_session_create: If browserbaseSessionID is provided, the service must find an existing stagehand_sessions row with browserbase_session_id=browserbaseSessionID and status in ('running','paused') in the caller workspace; otherwise create a new stagehand_sessions row with mode='multi' and status='initializing'.
- browserbase_session_create: If sessionId is provided, it is treated as a Browserbase vendor session id; reuse only if a stagehand_sessions row exists with browserbase_session_id=sessionId and mode='single' and status in ('running','paused'); else create a new single session and mark any prior non-closed single session in the workspace as closing/closed.
- multi_browserbase_stagehand_session_list returns only sessions with mode='multi' and status in ('initializing','running','paused','closing') for the workspace, including id, name, browserbase_session_id, created_at and last_activity_at (for age computation).
- multi_browserbase_stagehand_session_close requires sessionId to exist as stagehand_sessions.id with mode='multi' and status not in ('closed'); it transitions the session to 'closing' then 'closed' and sets closed_at.
- browserbase_session_close closes the currently active single session for the workspace (latest mode='single' with status in ('initializing','running','paused','closing')), transitioning it to 'closing' then 'closed'. If none exists, it is a no-op.
- navigate/act/observe/extract/screenshot tools (single and multi variants) must only operate on a session with status in ('running','paused'); they create a session_steps row with the appropriate input_* fields populated and advance status queued->running->(succeeded|failed).
- multi_* tools select the target session by stagehand_sessions.id = parameters.sessionId; single tools target the workspace's current mode='single' active session.
- After a successful navigate step, stagehand_sessions.current_url must be updated to input_url and last_activity_at updated; after any step attempt (success/failure), last_activity_at must be updated.
- For observe tools, if returnAction is true, session_steps.output must include an actionable instruction string suitable for later act; if returnAction is false/omitted, output may omit that string.
- browserbase_screenshot must create an artifacts row of type='screenshot_png' linked to the producing session and step, and only mark it available after the blob is durably stored.
- Quota enforcement: Creating a new session or running a step must be rejected if workspaces.status != 'active' or if session_concurrency_limit would be exceeded by sessions in ('initializing','running','paused','closing') or if monthly_step_limit/monthly_session_minutes_limit (when nonzero) would be exceeded.
- Integrity: session_steps.sequence must be assigned atomically per session (no gaps required, but strictly increasing and unique per session).
- Data retention: When a session is closed, artifacts may be retained; deleting a session cascades to session_steps and artifacts per FK rules.