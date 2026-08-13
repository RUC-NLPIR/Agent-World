# Calculator — local MCP environment

This backend stores calculator evaluation requests and their computed results for auditability, rate limiting, and repeatability. The main workflow is: a client submits an expression to be evaluated, the system normalizes/parses it, evaluates it, stores the result (or error), and records API usage against an API key.

Repository: https://github.com/githejie/mcp-server-calculator
Homepage: https://smithery.ai/server/@githejie/mcp-server-calculator

## Datastore

- `api_keys.json` — Issued API keys used to authenticate callers and enforce per-key quotas for calculator evaluations. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'quota_daily_requests', 'quota_daily_compute_units', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: quota_daily_requests >= 0
  - constraint: quota_daily_compute_units >= 0
- `calc_requests.json` — An evaluation request created by calling the calculate tool, including the raw expression and normalized form used for evaluation. (25 rows; fields: ['id', 'api_key_id', 'expression', 'normalized_expression', 'expression_sha256', 'requested_at', 'status', 'client_ip', 'user_agent', 'compute_units', 'parse_ms', 'eval_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'rejected']
  - constraint: expression != ''
  - constraint: length(expression) <= 4096
  - constraint: compute_units >= 0
  - constraint: parse_ms >= 0
- `calc_results.json` — Result (success or failure) for a calc request, including numeric output or error details. (25 rows; fields: ['id', 'request_id', 'status', 'result_type', 'result_number', 'result_text', 'result_precision', 'error_code', 'error_message', 'error_position', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'rejected']
  - constraint: unique(request_id)
  - constraint: fk(request_id) references calc_requests(id) on delete cascade
  - constraint: ((status = 'succeeded') implies (error_code is null and error_message is null))
  - constraint: ((status in ('failed','rejected')) implies (error_code is not null))
- `api_key_usage_daily.json` — Per-API-key daily counters used to enforce quotas and provide basic usage analytics. (12 rows; fields: ['id', 'api_key_id', 'usage_date', 'request_count', 'compute_units', 'success_count', 'fail_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'locked']
  - constraint: unique(api_key_id, usage_date)
  - constraint: fk(api_key_id) references api_keys(id) on delete cascade
  - constraint: request_count >= 0
  - constraint: compute_units >= 0

## Business rules enforced by the tools

- The calculate tool must persist a calc_requests row with expression equal to the provided tool parameter expression.
- On accepting a request, the system must set calc_requests.status='queued', then transition to 'running', and finally to exactly one terminal status in {'succeeded','failed','rejected'}; transitions outside the declared lifecycle are invalid.
- Each calc_requests row must have at most one calc_results row; creating a second result for the same request_id must fail due to unique(request_id).
- normalized_expression must be derived deterministically from expression (e.g., trim, collapse whitespace); expression_sha256 must be SHA-256(normalized_expression).
- Expression length must not exceed 4096 characters; otherwise the request must be rejected with calc_requests.status='rejected' and a calc_results row with status='rejected' and error_code='EXPRESSION_TOO_LONG'.
- If api_key_id is present, the api_keys.status must be 'active' at request acceptance; otherwise the request must be rejected with error_code='API_KEY_INACTIVE'.
- If api_key_id is present, the system must increment (or upsert) api_key_usage_daily for that key and UTC usage_date at acceptance time; request_count and compute_units must not exceed the api_keys.quota_daily_requests and api_keys.quota_daily_compute_units respectively—exceeding either must reject the request with error_code='QUOTA_EXCEEDED'.
- compute_units must be computed from expression complexity (at minimum proportional to length); it must be non-negative and stored on calc_requests.
- For successful evaluations, calc_results must have status='succeeded' and must set either result_number (with result_type='number') or result_text (with result_type='string'), but not both.
- For failed or rejected evaluations, calc_results must set error_code (and optionally error_message and error_position) and must not set result_number/result_text.
- Deleting an api_keys record must cascade delete its api_key_usage_daily rows, and must set calc_requests.api_key_id to null to preserve request audit history.
- calc_requests.updated_at and calc_results.updated_at must be updated on every state change or mutation; created_at must be immutable once set.