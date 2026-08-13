# Weather — local MCP environment

This backend stores cached responses and request logs for a Weather API that provides state-level weather alerts and point forecasts by latitude/longitude. Main workflows are: (1) log each API request, (2) serve from cache when fresh, otherwise fetch from upstream (e.g., NWS), normalize and store alerts/forecasts, and (3) track API keys and enforce basic quotas/rate limits.

Repository: https://github.com/mcp-examples/weather
Homepage: https://smithery.ai/server/@mcp-examples/weather

## Datastore

- `api_keys.json` — API credentials used to access the service, including status and quota configuration. (18 rows; fields: ['id', 'workspace_name', 'key_hash', 'status', 'requests_per_minute_limit', 'requests_per_day_limit', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit >= 1 and requests_per_minute_limit <= 6000
  - constraint: requests_per_day_limit >= 1 and requests_per_day_limit <= 10000000
- `api_requests.json` — Immutable request log for auditing, analytics, troubleshooting, and quota enforcement for get-alerts and get-forecast. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'state', 'latitude', 'longitude', 'cache_key', 'served_from_cache', 'response_status_code', 'error_code', 'error_message', 'upstream_provider', 'upstream_request_url', 'upstream_status_code', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['get-alerts', 'get-forecast']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: latency_ms >= 0 and latency_ms <= 300000
  - constraint: response_status_code >= 100 and response_status_code <= 599
  - constraint: state is null or (length(state) = 2 and state = upper(state))
- `alert_snapshots.json` — Cached, normalized weather alerts by state, fetched from upstream and stored as a snapshot for fast reads. (18 rows; fields: ['id', 'state', 'status', 'fetched_at', 'expires_at', 'upstream_provider', 'upstream_etag', 'upstream_last_modified', 'alert_count', 'raw_payload', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'error']
  - constraint: unique(state, fetched_at)
  - constraint: length(state) = 2 and state = upper(state)
  - constraint: alert_count >= 0
  - constraint: expires_at >= fetched_at
- `forecast_snapshots.json` — Cached point forecast snapshots for a lat/lon location. Stores normalized metadata plus full upstream payload for serving get-forecast. (20 rows; fields: ['id', 'latitude', 'longitude', 'geohash7', 'status', 'fetched_at', 'expires_at', 'upstream_provider', 'upstream_grid_id', 'upstream_grid_x', 'upstream_grid_y', 'timezone', 'period_count', 'raw_payload', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'error']
  - constraint: latitude >= -90 and latitude <= 90
  - constraint: longitude >= -180 and longitude <= 180
  - constraint: period_count >= 0
  - constraint: expires_at >= fetched_at

## Business rules enforced by the tools

- get-alerts(state): state must be exactly 2 characters and uppercase A-Z; requests that fail validation must be logged in api_requests with tool_name='get-alerts', response_status_code=400, error_code='VALIDATION_ERROR'.
- get-forecast(latitude, longitude): latitude must be in [-90, 90] and longitude in [-180, 180]; requests that fail validation must be logged in api_requests with tool_name='get-forecast', response_status_code=400, error_code='VALIDATION_ERROR'.
- For get-alerts, the cache lookup key must be 'alerts:' + state. For get-forecast, the cache lookup key must be 'forecast:' + round(latitude, 4) + ',' + round(longitude, 4) (rounding is part of the cache policy).
- A cached snapshot may be served only when status='fresh' and expires_at > now(); otherwise the service must attempt an upstream refresh and set the prior snapshot status to 'stale' (unless replaced) or record an 'error' snapshot on upstream failure.
- On upstream success for alerts, a new alert_snapshots row must be inserted with status='fresh', fetched_at=now(), expires_at=now()+ttl, raw_payload set to upstream JSON, and alert_count matching the number of alert features/items parsed from raw_payload.
- On upstream success for forecasts, a new forecast_snapshots row must be inserted with status='fresh', fetched_at=now(), expires_at=now()+ttl, raw_payload set to upstream JSON, and period_count matching the number of forecast periods parsed from raw_payload.
- Every tool invocation must create exactly one api_requests row (even if served from cache), including served_from_cache, response_status_code, latency_ms, and the tool parameters mapped into the appropriate columns.
- Requests must be rejected with response_status_code=429 and error_code='RATE_LIMITED' when the calling api_key exceeds requests_per_minute_limit (sliding window) or requests_per_day_limit (UTC day); rejected calls must still be logged in api_requests.
- api_keys with status in ('suspended','revoked') must not be allowed to call tools; such calls must return 403 and be logged with error_code='KEY_INACTIVE'.
- Data retention: api_requests may be partitioned by created_at and retained for at least 30 days; snapshots may be retained longer for debugging, but only the freshest snapshot per cache key should be preferred for serving.