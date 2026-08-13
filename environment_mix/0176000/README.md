# Claude Code Execution Server — local MCP environment

This backend powers a Claude Code Execution Server that accepts natural-language prompts and optionally a working folder, then runs a Claude CLI-backed agent to perform code, file, git, and terminal operations. It stores execution requests, resulting outputs/artifacts, and enforces access control, path safety, and quotas per API key/workspace.

Repository: https://github.com/steipete/claude-code-mcp
Homepage: https://smithery.ai/server/@steipete/claude-code-mcp

## Datastore

- `workspaces.json` — Tenant boundary for organizing API keys, execution sessions, and their retained artifacts/logs. (18 rows; fields: ['id', 'name', 'status', 'allowed_work_folders', 'retention_days', 'max_concurrent_runs', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: retention_days between 1 and 365
  - constraint: max_concurrent_runs between 1 and 100
  - constraint: each allowed_work_folders[i] must be an absolute path and normalized (no '..')
- `api_keys.json` — API keys used to authenticate requests to the Claude Code Execution Server; includes quota and revocation state. (18 rows; fields: ['id', 'workspace_id', 'key_hash', 'name', 'status', 'scopes', 'rate_limit_rpm', 'monthly_run_limit', 'monthly_token_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key(workspace_id) references workspaces(id)
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: rate_limit_rpm between 1 and 6000
- `agent_runs.json` — Each invocation of the claude_code tool; stores the prompt, optional workFolder, execution metadata, and final response. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'prompt', 'work_folder', 'status', 'requested_at', 'started_at', 'finished_at', 'exit_code', 'error_message', 'response_text', 'usage_tokens_estimated', 'runtime_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired']
  - constraint: foreign key(workspace_id) references workspaces(id)
  - constraint: foreign key(api_key_id) references api_keys(id)
  - constraint: prompt length between 1 and 100000
  - constraint: work_folder is null or (is absolute path and normalized and within one of workspaces.allowed_work_folders)
- `run_events.json` — Append-only structured event log for each agent run, including tool actions (file ops, git, terminal), streaming output chunks, and errors. (18 rows; fields: ['id', 'run_id', 'sequence', 'event_type', 'message', 'data', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['run_queued', 'run_started', 'run_finished', 'stdout', 'stderr', 'file_read', 'file_write', 'file_edit', 'file_list', 'file_delete', 'file_move', 'file_copy', 'git', 'terminal', 'image_ocr', 'policy_denied', 'error']
  - constraint: foreign key(run_id) references agent_runs(id) on delete cascade
  - constraint: unique(run_id, sequence)
  - constraint: sequence >= 1
  - constraint: if event_type in ('file_read','file_write','file_edit','file_delete','file_move','file_copy','file_list') then data.path must be present and absolute
- `run_artifacts.json` — Files or blobs produced/collected during a run (e.g., patches, logs, screenshots, OCR outputs). Stores metadata; content may live in object storage. (18 rows; fields: ['id', 'run_id', 'kind', 'name', 'content_type', 'byte_size', 'sha256', 'storage_url', 'inline_text', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'redacted', 'deleted']
  - constraint: foreign key(run_id) references agent_runs(id) on delete cascade
  - constraint: unique(run_id, name)
  - constraint: byte_size >= 0 and byte_size <= 1073741824
  - constraint: sha256 matches '^[a-f0-9]{64}$'

## Business rules enforced by the tools

- A claude_code tool call MUST create exactly one agent_runs row with prompt = parameters.prompt and work_folder = parameters.workFolder (or null if omitted).
- If parameters.workFolder is provided it MUST be an absolute, normalized path and MUST have a prefix that matches one of workspaces.allowed_work_folders for the associated workspace; otherwise the run MUST be rejected or marked failed with a policy_denied run_event.
- api_keys.status MUST be 'active' and workspaces.status MUST be 'active' for a run to transition from queued to running.
- Concurrency enforcement: for each workspace, count(agent_runs where status in ('queued','running')) MUST NOT exceed workspaces.max_concurrent_runs; excess requests MUST be rejected or left queued without starting.
- Rate limit enforcement: per api_key_id, the number of new agent_runs created in any rolling 60-second window MUST NOT exceed api_keys.rate_limit_rpm.
- Monthly quotas: per api_key_id and calendar month, total runs created MUST NOT exceed api_keys.monthly_run_limit (unless limit=0 meaning unlimited is NOT allowed; here 0 means 'no runs allowed'), and sum(usage_tokens_estimated) MUST NOT exceed api_keys.monthly_token_limit (0 means no tokens allowed).
- Status transitions MUST follow the declared lifecycle transitions for agent_runs and workspaces and api_keys; direct transitions (e.g., queued->succeeded) are invalid.
- When an agent_run status becomes one of ('succeeded','failed','cancelled','expired'), finished_at MUST be set and runtime_ms MUST be computed as (finished_at - started_at or requested_at).
- run_events.sequence MUST be strictly increasing per run_id; event insertions MUST be append-only (no updates) except for redaction where message/data may be replaced and updated_at changed.
- Artifact retention: a background job MUST mark run_artifacts.status='deleted' and may null storage_url/inline_text for runs older than workspaces.retention_days, and it MUST mark agent_runs.status='expired' only if the run is still queued/running beyond a configured max wall time.
- Sensitive data controls: if a run_event contains file content or command output, the service MUST support redaction by setting run_artifacts.status='redacted' or editing run_events.message/data in a redaction-safe manner (append-only plus redaction marker).