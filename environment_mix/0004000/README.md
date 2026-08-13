# Time Server — local MCP environment

This backend supports a simple time utility API that returns the current Unix timestamp and converts a provided Unix timestamp into a human-readable date string. The primary workflows are (1) servicing anonymous or authenticated requests with low latency and (2) recording request telemetry for rate limiting, auditing, and operational analytics.

Repository: https://github.com/javilujann/TimeMCP
Homepage: https://smithery.ai/server/@javilujann/timemcp

## Datastore

- `api_keys.json` — API keys used to authenticate callers and enforce per-key quotas. Optional for anonymous usage, but modeled for a production-grade service. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'name', 'status', 'rate_limit_rpm', 'daily_limit', 'last_used_at', 'revoked_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: rate_limit_rpm >= 0
  - constraint: daily_limit >= 0
- `request_events.json` — Immutable per-request telemetry for the two tools (getTime and readableTime). Used for monitoring, debugging, and quota enforcement. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'request_payload', 'timestamp_input', 'response_payload', 'http_status', 'error_code', 'error_message', 'latency_ms', 'client_ip', 'user_agent', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `http_status`: ['200', '400', '401', '403', '429', '500']
  - constraint: tool_name in ('getTime','readableTime')
  - constraint: timestamp_input is null when tool_name = 'getTime'
  - constraint: timestamp_input is not null when tool_name = 'readableTime'
  - constraint: latency_ms >= 0
- `rate_limit_counters.json` — Aggregated counters used to enforce per-key rate limits (per-minute) and daily quotas without scanning raw request_events. (17 rows; fields: ['id', 'api_key_id', 'window_type', 'window_start', 'count', 'created_at', 'updated_at'])
  - lifecycle `window_type`: ['minute', 'day']
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: count >= 0
- `time_conversions.json` — Optional cache of readableTime conversions for repeated timestamps and consistent formatting/versioning. Also supports analytics by timestamp ranges. (18 rows; fields: ['id', 'timestamp', 'format_pattern', 'timezone', 'readable_text', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'invalidated']
  - constraint: unique(timestamp, format_pattern, timezone)
  - constraint: timestamp >= -62135596800
  - constraint: timestamp <= 253402300799
  - constraint: timezone <> ''

## Business rules enforced by the tools

- getTime creates a request_events row with tool_name='getTime' and request_payload={}, and must store a numeric Unix timestamp in response_payload (seconds since epoch).
- readableTime requires timestamp in the request; the service must reject requests where timestamp is null or not a finite number (recording a request_events row with http_status=400).
- For readableTime, the request_events.timestamp_input field must equal the provided timestamp argument and response_payload must include the rendered human-readable string.
- If an api_key is provided, it must exist and have status='active'; otherwise the request is rejected with http_status=401 or 403 and recorded in request_events.
- Per api_key_id, the service must enforce api_keys.rate_limit_rpm using rate_limit_counters(window_type='minute') and api_keys.daily_limit using rate_limit_counters(window_type='day'); if exceeded, respond with http_status=429 and record the event.
- When a request with an api_key_id is successfully processed or rejected due to limits, the appropriate rate_limit_counters row for the current minute/day must be upserted and incremented atomically to prevent race conditions.
- If the service uses caching for readableTime, it may upsert into time_conversions where (timestamp, format_pattern, timezone) matches; only rows with status='valid' may be used to serve cached responses.
- Only the defined output format is permitted for readableTime; any change to formatting must bump format_pattern and invalidate prior cached rows by transitioning status from 'valid' to 'invalidated'.
- All foreign keys must maintain referential integrity: request_events.api_key_id and rate_limit_counters.api_key_id must reference api_keys.id when non-null.