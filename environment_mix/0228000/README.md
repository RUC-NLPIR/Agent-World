# Sequential Thinking Multi-Agent System — local MCP environment

This backend stores conversational “sequential thinking” runs that decompose a user objective into ordered steps, optionally delegating steps to specialized agents. The main workflow is: create a run, generate step-by-step thoughts and agent actions, then finalize with an outcome and store trace/metrics for auditing and replay.

Repository: https://github.com/FradSer/mcp-server-mas-sequential-thinking
Homepage: https://smithery.ai/server/@FradSer/mcp-server-mas-sequential-thinking

## Datastore

- `runs.json` — One invocation/session of the Sequential Thinking Multi-Agent System. Holds the top-level objective, lifecycle state, and final outcome for replay/audit. (19 rows; fields: ['id', 'status', 'input_prompt', 'final_output', 'error_code', 'error_message', 'started_at', 'completed_at', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'cancelled']
  - constraint: status IN ('queued','running','completed','failed','cancelled')
  - constraint: completed_at IS NULL OR started_at IS NOT NULL
  - constraint: status IN ('completed','failed','cancelled') => completed_at IS NOT NULL
  - constraint: status = 'running' => started_at IS NOT NULL
- `agents.json` — Catalog of available agents used by the sequential thinking system (planner, researcher, critic, etc.). (17 rows; fields: ['id', 'name', 'role', 'enabled', 'config', 'created_at', 'updated_at'])
  - lifecycle `enabled`: ['true', 'false']
  - constraint: unique(name)
  - constraint: role IN ('planner','executor','researcher','critic','summarizer','router','tooling')
  - constraint: name <> ''
- `steps.json` — Ordered steps within a run. Each step contains the system’s intermediate reasoning artifact (stored for replay/audit) and the step outcome. (18 rows; fields: ['id', 'run_id', 'step_index', 'status', 'agent_id', 'instruction', 'thought', 'result', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'skipped', 'cancelled']
  - constraint: foreign key(run_id) references runs(id) on delete cascade
  - constraint: foreign key(agent_id) references agents(id)
  - constraint: unique(run_id, step_index)
  - constraint: step_index >= 0
- `tool_calls.json` — Tool invocations performed during a step (including any web/search actions), capturing inputs, outputs, timing, and status. (18 rows; fields: ['id', 'run_id', 'step_id', 'sequence_index', 'tool_name', 'status', 'input', 'output', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(run_id) references runs(id) on delete cascade
  - constraint: foreign key(step_id) references steps(id) on delete cascade
  - constraint: unique(step_id, sequence_index)
  - constraint: sequence_index >= 0
- `api_requests.json` — Audit/telemetry for each external call to the exposed MCP tool endpoint `sequentialthinking`. Because the tool has no parameters, this mainly captures timing, caller metadata, and the run created/used. (19 rows; fields: ['id', 'tool', 'run_id', 'idempotency_key', 'caller', 'request_headers', 'request_body', 'response_body', 'http_status', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `http_status`: ['100-599']
  - constraint: tool = 'sequentialthinking'
  - constraint: unique(idempotency_key) WHERE idempotency_key IS NOT NULL
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: http_status IS NULL OR (http_status >= 100 AND http_status <= 599)

## Business rules enforced by the tools

- Invoking tool `sequentialthinking` with an empty parameters object MUST create an api_requests row with request_body = {} (or equivalent empty object) and tool = 'sequentialthinking'.
- A successful tool invocation MUST either (a) create a new runs row and link api_requests.run_id to it, or (b) reuse an existing run when a matching idempotency_key is provided; in either case api_requests.run_id MUST reference runs.id.
- A run MUST have steps with contiguous step_index starting at 0 once status becomes 'completed' (no gaps allowed).
- steps(run_id, step_index) MUST be unique; tool_calls(step_id, sequence_index) MUST be unique.
- Deleting a run MUST cascade delete its steps and tool_calls, and MUST set api_requests.run_id to NULL or cascade delete api_requests depending on retention policy; this model enforces FK integrity via explicit constraints (default: allow api_requests to retain and set run_id NULL if run deleted).
- A step cannot transition to 'running' unless its parent run.status is 'running'. A run cannot transition to 'completed' unless all its non-skipped steps are in status 'completed'.
- Agents assigned to steps MUST have enabled = true at assignment time; disabled agents cannot be newly assigned but may remain referenced for historical runs.
- duration_ms fields MUST be non-negative integers when present; large payload text fields MUST not exceed the configured maximum lengths enforced by constraints.