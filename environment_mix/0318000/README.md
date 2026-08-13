# Weather MCP Tool — local MCP environment

This backend stores weather provider configurations, normalized locations (cities), and cached current/forecast weather responses served through two MCP tools. Main workflows: resolve a city to a location, fetch weather from an upstream provider when cache is stale, store the result, and serve responses while tracking usage for quota/rate limiting.

Repository: https://github.com/MrCare/mcp_tool
Homepage: https://smithery.ai/server/@MrCare/mcp_tool

## Datastore

- `api_keys.json` — Client credentials for accessing the Weather MCP Tool, with per-key quotas and lifecycle controls. (11 rows; fields: ['id', 'key_hash', 'label', 'status', 'plan', 'requests_per_minute_limit', 'requests_per_day_limit', 'daily_reset_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit >= 1
  - constraint: requests_per_day_limit >= 1
- `locations.json` — Canonical location records used to resolve city input (Chinese/English) to a stable identifier and coordinates. (18 rows; fields: ['id', 'city_name_en', 'city_name_zh_cn', 'country_code', 'admin1', 'latitude', 'longitude', 'timezone', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: latitude between -90 and 90
  - constraint: longitude between -180 and 180
  - constraint: unique(city_name_en, country_code, admin1)
  - constraint: unique(city_name_zh_cn, country_code, admin1) where city_name_zh_cn is not null
- `weather_requests.json` — Immutable request log for get_weather and get_weather_forecast calls, including normalized inputs (city, units, lang, days) and resulting cache/provider behavior. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'input_city_raw', 'location_id', 'days', 'units', 'lang', 'status', 'served_from_cache', 'cache_entry_id', 'provider_name', 'provider_http_status', 'error_code', 'error_message', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'rate_limited']
  - constraint: days is null or (days >= 1 and days <= 5)
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: provider_http_status is null or (provider_http_status >= 100 and provider_http_status <= 599)
  - constraint: tool_name = 'get_weather_forecast' implies days is not null
- `weather_cache.json` — Cached current conditions and forecast payloads keyed by location, tool, units, language, and (for forecasts) days, with TTL-based validity. (17 rows; fields: ['id', 'location_id', 'tool_name', 'days', 'units', 'lang', 'provider_name', 'provider_payload', 'observed_at', 'valid_from', 'valid_until', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'purged']
  - constraint: valid_until > valid_from
  - constraint: days is null or (days >= 1 and days <= 5)
  - constraint: tool_name = 'get_weather' implies days is null
  - constraint: tool_name = 'get_weather_forecast' implies days is not null
- `usage_counters.json` — Aggregated per-key usage for enforcing rate limits and daily quotas without scanning request logs. (17 rows; fields: ['id', 'api_key_id', 'window_start', 'window_type', 'request_count', 'success_count', 'error_count', 'rate_limited_count', 'created_at', 'updated_at'])
  - lifecycle `window_type`: ['minute', 'day']
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: request_count >= 0
  - constraint: success_count >= 0
  - constraint: error_count >= 0

## Business rules enforced by the tools

- Each tool invocation (get_weather, get_weather_forecast) must create exactly one weather_requests row with tool_name set accordingly.
- For get_weather_forecast, the system must treat days as an integer in [1,5]; if absent, it must default to a configured value (e.g., 3) and persist that resolved value in weather_requests.days.
- For get_weather_forecast, units must be one of {metric, imperial} and lang must be one of {zh_cn, en}; if absent, defaults must be applied and persisted in weather_requests.units and weather_requests.lang.
- For get_weather (no parameters), the system must use implementation-defined defaults (e.g., a default city, server-configured location, or IP-derived location); the resolved location_id (if any) must be stored in weather_requests.location_id.
- Before calling an upstream provider, the system must attempt to serve from weather_cache using key (location_id, tool_name, days, units, lang) where status='fresh' and valid_until > now(); if served from cache, weather_requests.served_from_cache=true and cache_entry_id must reference that row.
- If no fresh cache entry exists, the system must fetch from the configured provider, upsert a weather_cache row (or create a new one) with a new valid_from/valid_until TTL window, and mark it status='fresh'; any previous non-purged entry for the same key must be transitioned to 'stale' or 'purged'.
- API key enforcement: requests must be rejected (recorded as weather_requests.status='rate_limited') when usage_counters for the current minute exceeds api_keys.requests_per_minute_limit or the current day exceeds api_keys.requests_per_day_limit.
- Requests using an api_keys.status other than 'active' must be rejected and recorded as weather_requests.status='failed' with error_code indicating authentication/authorization failure.
- Foreign key integrity must be enforced: weather_requests.api_key_id must exist in api_keys; weather_cache.location_id must exist in locations; weather_requests.location_id, cache_entry_id when present must reference valid rows.
- Cache uniqueness must be enforced such that at most one non-purged weather_cache row exists per (location_id, tool_name, days, units, lang).