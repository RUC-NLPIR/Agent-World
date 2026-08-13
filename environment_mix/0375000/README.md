# Advanced Calculator Server — local MCP environment

This backend stores authenticated clients (API keys) and an auditable ledger of calculator operations executed by the Advanced Calculator Server. Each tool call creates an operation record with normalized arguments and computed results, while usage accounting enforces per-key quotas and supports basic analytics and abuse prevention.

Repository: https://github.com/alan5543/calculator-mcp
Homepage: https://smithery.ai/server/@alan5543/calculator-mcp

## Datastore

- `api_keys.json` — Issued API keys used to authenticate requests to calculator tools, with lifecycle status and quota configuration. (27 rows; fields: ['id', 'key_hash', 'key_prefix', 'owner_label', 'status', 'rate_limit_rpm', 'daily_request_quota', 'metadata', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: rate_limit_rpm >= 1 AND rate_limit_rpm <= 60000
  - constraint: daily_request_quota >= 0 AND daily_request_quota <= 100000000
- `calculator_operations.json` — Immutable log of each calculator tool invocation, including normalized inputs, outputs, and execution status. (33 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'args', 'result_number', 'result_boolean', 'result_tuple', 'result_complex_tuple', 'error_code', 'error_message', 'duration_ms', 'request_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'rejected']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: duration_ms is null OR (duration_ms >= 0 AND duration_ms <= 600000)
  - constraint: status='succeeded' implies (result_number is not null OR result_boolean is not null OR result_tuple is not null OR result_complex_tuple is not null)
  - constraint: status in ('failed','rejected') implies error_code is not null
- `daily_usage.json` — Per-API-key daily counters used for quota enforcement and reporting. (32 rows; fields: ['id', 'api_key_id', 'usage_date', 'request_count', 'success_count', 'failed_count', 'rejected_count', 'created_at', 'updated_at'])
  - lifecycle `usage_state`: ['open', 'finalized']
  - constraint: fk(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, usage_date)
  - constraint: request_count >= 0
  - constraint: success_count >= 0
- `rate_limit_buckets.json` — Rolling per-minute rate limit buckets per API key to enforce rate_limit_rpm. (31 rows; fields: ['id', 'api_key_id', 'bucket_minute', 'request_count', 'created_at', 'updated_at'])
  - lifecycle `bucket_state`: ['active', 'expired']
  - constraint: fk(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, bucket_minute)
  - constraint: request_count >= 0

## Business rules enforced by the tools

- Each tool invocation (add, sub, mul, div, power, square_root, factorial, log, sin, cos, tan, degrees_to_radians, radians_to_degrees, gcd, lcm, is_prime, quadratic_roots) must insert exactly one row into calculator_operations with tool_name matching the invoked tool and args containing exactly the provided parameters (plus defaults applied by the server, e.g., log.base defaulting to 2.718281828459045 when omitted).
- Requests must be authorized by an api_keys row with status='active'; otherwise the operation must be recorded with status='rejected' and error_code='UNAUTHORIZED'.
- Before execution, the server must enforce per-minute rate limiting using rate_limit_buckets; if the request would exceed api_keys.rate_limit_rpm for the current minute bucket, record the operation with status='rejected' and error_code='RATE_LIMITED'.
- Before execution, the server must enforce daily quotas using daily_usage; if daily_usage.request_count would exceed api_keys.daily_request_quota for the current UTC day, record the operation with status='rejected' and error_code='QUOTA_EXCEEDED'.
- Validation errors must be recorded with status='rejected' and error_code='VALIDATION_ERROR' (e.g., missing required fields; wrong numeric type in args).
- div must reject b=0 with status='failed' and error_code='DIVIDE_BY_ZERO'.
- square_root must fail for x < 0 with error_code='NEGATIVE_SQRT'.
- factorial must reject n < 0 with error_code='NEGATIVE_FACTORIAL' (and must require integer n as per tool schema).
- log must fail when x <= 0 with error_code='LOG_NON_POSITIVE' and must fail when base <= 0 or base = 1 with error_code='LOG_INVALID_BASE'.
- gcd and lcm must require integer inputs; gcd(0,0) must be recorded as failed with error_code='INVALID_GCD'; lcm(0,0) must be recorded as failed with error_code='INVALID_LCM'.
- quadratic_roots must fail when a = 0 with error_code='QUADRATIC_A_ZERO'; otherwise it must store results as either result_tuple (real roots) or result_complex_tuple (complex roots) with exactly two roots.
- On every non-unauthorized request (authorized key), daily_usage.request_count must increment by 1, and exactly one of success_count/failed_count/rejected_count must increment based on calculator_operations.status.
- calculator_operations rows are append-only for args/tool_name/api_key_id; only duration_ms, error_code, error_message, updated_at may be updated after insertion (e.g., to finalize timing/errors).