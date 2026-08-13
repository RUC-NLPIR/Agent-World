# Wait — local MCP environment

This backend supports a simple Wait API that pauses execution for a requested duration and records each wait invocation for auditing, rate-limiting, and operational observability. The main workflow is creating a wait request with a bounded duration, transitioning it through running to completed (or failed/cancelled), and optionally aggregating usage per API key.

Repository: https://github.com/automation-ai-labs/mcp-wait
Homepage: https://smithery.ai/server/@automation-ai-labs/mcp-wait

## Datastore

- `api_keys.json` — API credentials used to authenticate callers and associate wait requests with an owner and quota. (12 rows; fields: ['id', 'key_hash', 'name', 'status', 'rate_limit_per_minute', 'max_seconds_per_request', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute >= 1 AND rate_limit_per_minute <= 6000
  - constraint: max_seconds_per_request >= 0 AND max_seconds_per_request <= 300
  - constraint: revoked_at IS NULL OR status = 'revoked'
- `wait_requests.json` — Each invocation of the wait tool, including requested seconds and execution lifecycle. (18 rows; fields: ['id', 'api_key_id', 'seconds', 'status', 'requested_at', 'started_at', 'completed_at', 'actual_elapsed_ms', 'error_code', 'error_message', 'client_request_id', 'request_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'cancelled', 'failed']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: seconds >= 0 AND seconds <= 300
  - constraint: actual_elapsed_ms IS NULL OR actual_elapsed_ms >= 0
  - constraint: started_at IS NULL OR started_at >= requested_at
- `rate_limit_windows.json` — Rolling per-minute counters used to enforce per-API-key request limits for the wait tool. (18 rows; fields: ['id', 'api_key_id', 'window_start', 'request_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'sealed']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, window_start)
  - constraint: request_count >= 0
  - constraint: window_start = date_trunc('minute', window_start)

## Business rules enforced by the tools

- Tool `wait(seconds)` must create a wait_requests row with seconds equal to the request parameter and enforce 0 <= seconds <= 300.
- If the caller is authenticated, the request must be linked to api_keys.id; api_keys.status must be 'active' or the call is rejected.
- Per request, seconds must also be <= api_keys.max_seconds_per_request (which itself must be <= 300).
- Before transitioning a wait_request to 'running', increment (or create) the corresponding rate_limit_windows row for date_trunc('minute', now()) and ensure request_count does not exceed api_keys.rate_limit_per_minute; otherwise reject with a rate-limit error and do not start running.
- wait_requests.status transitions must follow the declared lifecycle; direct transitions from 'queued' to 'completed' are not permitted without entering 'running'.
- When a wait finishes successfully, set status='completed', completed_at=now(), and actual_elapsed_ms to a non-negative integer; actual_elapsed_ms should be within +/- 5% or 250ms (whichever is larger) of seconds*1000 unless the system is under load.
- If an internal error prevents waiting, set status='failed' and populate error_code and error_message; if cancelled by the server/shutdown, set status='cancelled' and completed_at.
- If client_request_id is provided, repeated calls with the same (api_key_id, client_request_id) must be treated idempotently by returning the existing wait_requests outcome rather than creating a new row.