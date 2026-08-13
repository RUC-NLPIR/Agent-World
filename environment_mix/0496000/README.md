# Math-MCP — local MCP environment

Math-MCP is a lightweight math microservice exposed via MCP tools. The backend primarily tracks clients (API keys), per-call tool executions (inputs/outputs/errors), and aggregated usage for quota/rate governance and auditing.

Repository: https://github.com/EthanHenrickson/math-mcp
Homepage: https://smithery.ai/server/@EthanHenrickson/math-mcp

## Datastore

- `api_keys.json` — Client credentials used to authenticate callers and apply quotas. Keys are hashed at rest; only a prefix is stored for display/debug. (12 rows; fields: ['id', 'key_prefix', 'key_hash', 'name', 'owner', 'status', 'allowed_tools', 'quota_calls_per_day', 'quota_numbers_per_call_max', 'rate_limit_per_minute', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_prefix)
  - constraint: quota_calls_per_day >= 0
  - constraint: quota_numbers_per_call_max >= 1
  - constraint: rate_limit_per_minute >= 0
- `tool_executions.json` — Audit log of each tool invocation, storing the tool name, validated inputs, outputs, and any error details. Serves debugging, billing/usage, and abuse monitoring. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'request_params', 'result_number', 'result_meta', 'error_code', 'error_message', 'latency_ms', 'numbers_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'validated', 'succeeded', 'failed']
  - constraint: fk(api_key_id) references api_keys.id on delete restrict
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: numbers_count is null or numbers_count >= 1
  - constraint: if tool_name in (sum,mean,median,mode,min,max) then request_params.numbers is array and numbers_count = len(request_params.numbers)
- `execution_numbers.json` — Child rows for tools that accept an array of numbers. Stored to support detailed auditing, reproducibility, and potential future analytics without relying on JSON parsing. (18 rows; fields: ['id', 'execution_id', 'position', 'value', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(execution_id) references tool_executions.id on delete cascade
  - constraint: unique(execution_id, position)
  - constraint: position >= 0
- `usage_daily.json` — Pre-aggregated daily usage per API key for quota enforcement and reporting. Updated on each execution completion (succeeded or failed). (18 rows; fields: ['id', 'api_key_id', 'date', 'calls_total', 'calls_succeeded', 'calls_failed', 'numbers_total', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'finalized']
  - constraint: fk(api_key_id) references api_keys.id on delete cascade
  - constraint: unique(api_key_id, date)
  - constraint: calls_total >= 0
  - constraint: calls_succeeded >= 0

## Business rules enforced by the tools

- Every tool call (add, subtract, multiply, division, sum, mean, median, mode, min, max, floor, ceiling, round) MUST create a tool_executions row with tool_name matching the invoked tool and request_params containing exactly the validated parameters (additionalProperties=false).
- For multiply, the input parameter name MUST be persisted as 'SecondNumber' (capital S) to match the published JSON schema; requests using 'secondNumber' MUST be rejected with VALIDATION_ERROR.
- For sum/mean/median/mode/min/max, request_params.numbers MUST have length >= 1 and length MUST be <= api_keys.quota_numbers_per_call_max; otherwise reject with VALIDATION_ERROR or QUOTA_EXCEEDED.
- For division, denominator MUST NOT be 0; if denominator=0, mark execution failed with error_code=DIVIDE_BY_ZERO and do not set result_number.
- For every successful execution, status MUST transition received -> validated -> succeeded, result_number MUST be set, and error_code/error_message MUST be null.
- For every failed execution, status MUST transition from received or validated to failed; error_code MUST be set; result_number MUST be null.
- If api_keys.allowed_tools is non-empty, the requested tool_name MUST be included; otherwise reject with error_code=TOOL_NOT_ALLOWED.
- If api_keys.status is not active, all requests using that key MUST be rejected and a failed tool_executions row MUST be recorded with error_code=KEY_INACTIVE.
- Daily quota enforcement: before accepting a call, the system MUST ensure usage_daily.calls_total + 1 <= api_keys.quota_calls_per_day for the current UTC date; otherwise reject with QUOTA_EXCEEDED and still record the attempt as a failed execution (counted in calls_total/calls_failed).
- On completion of each execution (succeeded or failed), usage_daily MUST be upserted for (api_key_id, date) and increment calls_total and calls_succeeded/calls_failed accordingly; numbers_total MUST be incremented by numbers_count when applicable.
- For array-based tools, execution_numbers rows MUST be created for each input number with unique (execution_id, position) and position matching the original order; tool_executions.numbers_count MUST equal the number of child rows.
- Foreign key integrity MUST be enforced: tool_executions.api_key_id must reference an existing api_keys row; execution_numbers.execution_id must reference an existing tool_executions row.