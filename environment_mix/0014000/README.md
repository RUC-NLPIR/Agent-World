# Weather MCP Server — local MCP environment

This backend stores invocations of a single Weather MCP tool and the resulting weather payloads returned to clients. It also tracks client identities (API keys) and enforces basic usage quotas and rate limits for the weather endpoint.

Repository: https://github.com/CodeByWaqas/weather-mcp-server
Homepage: https://smithery.ai/server/@CodeByWaqas/weather-mcp-server

## Datastore

- `api_keys.json` — Client credentials used to authenticate/identify callers of the Weather MCP server and apply quota/rate limits. (34 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'owner_type', 'owner_id', 'status', 'requests_per_minute_limit', 'requests_per_day_limit', 'usage_day', 'usage_day_count', 'usage_minute', 'usage_minute_count', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: requests_per_minute_limit >= 0
  - constraint: requests_per_day_limit >= 0
- `weather_requests.json` — An invocation of the MCP tool `weather`. Since the tool takes no parameters, this primarily records caller context and execution metadata. (34 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'request_source', 'caller_ip', 'user_agent', 'idempotency_key', 'started_at', 'finished_at', 'duration_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'throttled']
  - constraint: tool_name = 'weather'
  - constraint: unique(api_key_id, idempotency_key) where idempotency_key is not null
  - constraint: duration_ms >= 0
- `weather_responses.json` — Weather payload produced for a given request, including the raw upstream response and normalized fields for querying/monitoring. (34 rows; fields: ['id', 'weather_request_id', 'provider', 'provider_request_id', 'location_name', 'latitude', 'longitude', 'timezone', 'observed_at', 'temperature_c', 'humidity_pct', 'wind_speed_mps', 'condition_code', 'condition_text', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `provider`: ['open_meteo', 'openweathermap', 'weatherapi', 'mock', 'unknown']
  - constraint: unique(weather_request_id)
  - constraint: latitude between -90 and 90 when latitude is not null
  - constraint: longitude between -180 and 180 when longitude is not null
  - constraint: humidity_pct between 0 and 100 when humidity_pct is not null
- `provider_configs.json` — Configuration for upstream weather providers (API base URLs, credentials references, and feature flags). Used by the weather tool implementation to select and call providers. (12 rows; fields: ['id', 'provider', 'status', 'base_url', 'auth_type', 'api_key_ref', 'priority', 'timeout_ms', 'max_retries', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(provider)
  - constraint: priority >= 0
  - constraint: timeout_ms between 100 and 120000
  - constraint: max_retries between 0 and 10

## Business rules enforced by the tools

- Invoking the `weather` tool MUST create a weather_requests row with tool_name='weather' and status='received' before any upstream call is made.
- A weather_requests row MUST transition status in order: received -> running -> (succeeded|failed) OR received -> throttled OR received -> failed; no other transitions are allowed.
- For each weather_requests row with status='succeeded', exactly one weather_responses row MUST exist (enforced by unique(weather_request_id)).
- When an api_key_id is present, the system MUST enforce requests_per_minute_limit and requests_per_day_limit from api_keys; if exceeded, the request MUST be recorded with status='throttled' and MUST NOT call an upstream provider.
- api_keys.key_hash MUST be unique and raw API keys MUST NOT be stored in any collection.
- Provider selection for fulfilling a request MUST choose the lowest-priority provider_configs row with status='active'; if none are active, the request MUST fail with error_code='NO_PROVIDER_AVAILABLE'.
- weather_responses.raw_payload MUST be stored exactly as returned to the MCP client for audit/debugging; normalized fields (temperature_c, humidity_pct, etc.) may be null if not present in the payload.
- If idempotency_key is provided, repeated calls with the same (api_key_id, idempotency_key) MUST return the previously stored response and MUST NOT create a second weather_requests row (enforced by uniqueness constraint).