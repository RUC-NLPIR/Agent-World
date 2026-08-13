# Code Runner — local MCP environment

This backend powers a secure code-execution API for JavaScript and Python. It stores execution requests (including inputs, variables, resource limits, and networking flags), validation-only scans, and the platform capability configuration used to answer capability queries and enforce security/quota constraints.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@dravidsajinraj-iex/code-runner-mcp

## Datastore

- `api_keys.json` — API keys used to authenticate callers and apply per-key quotas/limits for code execution and validation. (26 rows; fields: ['id', 'key_hash', 'key_prefix', 'name', 'status', 'default_timeout_ms', 'max_timeout_ms', 'default_memory_mb', 'max_memory_mb', 'allow_networking', 'rate_limit_per_min', 'daily_exec_limit', 'daily_validate_limit', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: max_timeout_ms <= 60000
  - constraint: default_timeout_ms > 0
- `execution_requests.json` — Every code execution request (with or without variables). Stores resource limits, input, and resulting output/errors. (38 rows; fields: ['id', 'api_key_id', 'tool_name', 'language', 'code', 'stdin', 'variables_raw', 'variables_json', 'timeout_ms', 'memory_limit_mb', 'enable_networking', 'status', 'reject_reason', 'reject_details', 'exit_code', 'stdout', 'stderr', 'error_type', 'error_message', 'duration_ms', 'billed_units', 'requested_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'rejected', 'cancelled']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: tool_name in ('execute_code','execute_code_with_variables')
  - constraint: timeout_ms >= 1
  - constraint: timeout_ms <= 60000
- `code_validations.json` — Validation-only checks for security and syntax issues without executing code. (33 rows; fields: ['id', 'api_key_id', 'language', 'code', 'status', 'is_secure', 'is_syntax_valid', 'issues', 'error_message', 'requested_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'passed', 'failed', 'error']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: status in ('queued','running','passed','failed','error')
- `capability_profiles.json` — Versioned service capability configuration used to answer get_capabilities and enforce hard limits/policies. (13 rows; fields: ['id', 'name', 'status', 'supported_languages', 'max_timeout_ms', 'max_memory_mb', 'networking_supported', 'security_policy', 'sandbox_engine', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'deprecated']
  - constraint: unique(name)
  - constraint: max_timeout_ms <= 60000
  - constraint: max_timeout_ms >= 1
  - constraint: max_memory_mb <= 512
- `usage_counters.json` — Aggregated per-key usage for enforcing daily quotas and basic rate-limit accounting. (31 rows; fields: ['id', 'api_key_id', 'day', 'execute_count', 'validate_count', 'execution_ms_total', 'created_at', 'updated_at'])
  - lifecycle `day`: []
  - constraint: foreign key(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, day)
  - constraint: execute_count >= 0
  - constraint: validate_count >= 0

## Business rules enforced by the tools

- execute_code and execute_code_with_variables must create a row in execution_requests with tool_name matching the invoked tool, language/code populated, and requested_at/created_at set.
- If timeout is omitted, execution_requests.timeout_ms must be set to api_keys.default_timeout_ms; otherwise it must be min(request.timeout, api_keys.max_timeout_ms, capability_profiles.max_timeout_ms) and must not exceed 60000.
- If memoryLimit is omitted, execution_requests.memory_limit_mb must be set to api_keys.default_memory_mb; otherwise it must be min(request.memoryLimit, api_keys.max_memory_mb, capability_profiles.max_memory_mb) and must not exceed 512.
- If enableNetworking=true, it must be allowed by both capability_profiles.networking_supported=true and api_keys.allow_networking=true; otherwise the request must be rejected with status='rejected' and reject_reason='networking_not_allowed'.
- execute_code_with_variables: variables may be provided as an object or a JSON string; the service must store the original in variables_raw and, when parseable, the normalized object in variables_json. If variables cannot be parsed as JSON object, the request must be rejected with reject_reason='invalid_variables_json'.
- execute_code (without variables) must store variables_raw and variables_json as NULL.
- Before moving an execution_request from queued->running, the service must ensure api_keys.status='active' and daily quotas are not exceeded: usage_counters.execute_count < api_keys.daily_exec_limit for the UTC day bucket; otherwise set status='rejected' and reject_reason='quota_exceeded'.
- validate_code must create a row in code_validations; before running, enforce api_keys.status='active' and usage_counters.validate_count < api_keys.daily_validate_limit for the UTC day bucket; otherwise set status='error' with error_message='quota_exceeded' (or reject at ingress depending on implementation).
- validate_code must not execute the code; it may produce issues array (possibly empty) and must end in status passed/failed/error with finished_at set.
- For execution_requests, when status transitions to succeeded/failed/timed_out/cancelled/rejected, finished_at must be set and updated_at advanced; duration_ms must be non-null for succeeded/failed/timed_out.
- get_capabilities must read from the single active capability_profiles row and return supported_languages plus limits derived from that row (max_timeout_ms/max_memory_mb) and whether networking_supported is available.
- usage_counters must be upserted (unique(api_key_id, day)) on each incoming request: increment execute_count for execute tools, increment validate_count for validate_code, and add duration_ms to execution_ms_total upon execution completion.