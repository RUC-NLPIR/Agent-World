# Korea Weather — local MCP environment

This backend stores Korea weather API requests and their resulting nowcast observations and forecasts, with caching and rate/usage tracking. The main workflows are: clients call one of three endpoints, the service resolves a location (optional), fetches/normalizes provider data, stores a response payload for cache reuse, and records usage for operational monitoring and quota enforcement.

Repository: https://github.com/ohhan777/korea_weather
Homepage: https://smithery.ai/server/@ohhan777/korea_weather

## Datastore

- `api_clients.json` — Represents calling applications/users (even if unauthenticated in the public MCP surface), used for rate limiting, abuse control, and analytics. (25 rows; fields: ['id', 'client_name', 'client_type', 'api_key_hash', 'status', 'daily_quota_requests', 'per_minute_limit', 'last_seen_ip', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(api_key_hash) where api_key_hash is not null
  - constraint: daily_quota_requests between 0 and 1000000
  - constraint: per_minute_limit between 0 and 60000
- `locations.json` — Normalized locations used for caching and mapping to KMA grid coordinates (if needed). Tools accept no explicit parameters in the surface, but the service may infer location from deployment configuration, caller context, or defaults. (32 rows; fields: ['id', 'source', 'latitude', 'longitude', 'kma_grid_x', 'kma_grid_y', 'label', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: latitude is null or (latitude between -90 and 90)
  - constraint: longitude is null or (longitude between -180 and 180)
  - constraint: kma_grid_x is null or kma_grid_x between 1 and 2000
  - constraint: kma_grid_y is null or kma_grid_y between 1 and 2000
- `weather_requests.json` — Immutable request log for each tool call, including resolved location and cache decision. Serves operational auditing and usage-based throttling. (35 rows; fields: ['id', 'client_id', 'tool_name', 'location_id', 'request_params', 'resolved_latitude', 'resolved_longitude', 'cache_key', 'cache_hit', 'http_status', 'latency_ms', 'status', 'error_code', 'error_message', 'requested_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'served', 'failed']
  - constraint: cache_key length between 10 and 256
  - constraint: http_status is null or http_status between 100 and 599
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: resolved_latitude is null or (resolved_latitude between -90 and 90)
- `weather_responses.json` — Cached normalized provider responses for each tool. Allows serving repeated calls without hitting upstream KMA every time. Stores both raw payload and a pre-rendered string response (as the tools return str). (41 rows; fields: ['id', 'cache_key', 'tool_name', 'location_id', 'provider', 'provider_endpoint', 'base_datetime', 'valid_from', 'valid_to', 'response_text', 'raw_payload', 'status', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'expired', 'invalid']
  - constraint: unique(cache_key)
  - constraint: expires_at > created_at
  - constraint: response_text length between 1 and 50000
  - constraint: valid_from is null or valid_to is null or valid_to >= valid_from
- `usage_counters.json` — Aggregated usage counters per client and time bucket for enforcing per-minute and per-day limits and generating basic metrics. (29 rows; fields: ['id', 'client_id', 'bucket_type', 'bucket_start', 'request_count', 'served_count', 'failed_count', 'cache_hit_count', 'created_at', 'updated_at'])
  - lifecycle `bucket_type`: ['minute', 'day']
  - constraint: unique(client_id, bucket_type, bucket_start)
  - constraint: request_count >= 0
  - constraint: served_count >= 0
  - constraint: failed_count >= 0

## Business rules enforced by the tools

- Each tool call (get_nowcast_observation, get_short_term_forecast, get_nowcast_forecast) must create exactly one weather_requests row with tool_name set accordingly and request_params storing the received JSON object (currently {}).
- For get_short_term_forecast and get_nowcast_forecast, if lat/lon are introduced later, the service must validate latitude in [-90, 90] and longitude in [-180, 180] before resolving to KMA grid; if invalid, weather_requests.status becomes failed with error_code=INVALID_LOCATION and http_status=400.
- A cache_key must be computed deterministically from tool_name + resolved location (grid or lat/lon) + provider base time window; weather_requests.cache_key must match weather_responses.cache_key when served from cache.
- If a non-expired weather_responses row exists with matching cache_key and status in (fresh, stale) and expires_at > now(), the request should be served from cache (cache_hit=true) and weather_requests.status=served.
- When a cache entry expires (expires_at <= now()), it must not be served; the system must fetch upstream and either refresh the existing cache_key row (status back to fresh, updated response_text/raw_payload, updated expires_at) or mark old row expired and create a new one (but uniqueness(cache_key) requires update-in-place).
- On upstream/provider failures, the request must be marked failed with error_code in (PROVIDER_ERROR, TIMEOUT) and a 5xx/504 http_status; no weather_responses row may be created/updated to fresh for that cache_key on that attempt.
- Per-minute and per-day rate limits must be enforced using usage_counters: for each request, increment request_count in the relevant minute and day buckets; if the increment would exceed api_clients.per_minute_limit or api_clients.daily_quota_requests, the request must be rejected with error_code=RATE_LIMITED, http_status=429, and status=failed.
- If api_clients.status is suspended or deleted, all requests for that client must be rejected with http_status=403 and status=failed (error_code=RATE_LIMITED for suspended, INTERNAL_ERROR or a dedicated code if added later).
- weather_requests rows are immutable for request_params and requested_at after creation; only status, latency_ms, http_status, and error fields may be updated as the request completes.
- locations.status=inactive locations cannot be used to generate new cache entries; attempts must fail with INVALID_LOCATION unless a different active location is resolved.