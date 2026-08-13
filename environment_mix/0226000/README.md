# Weather Service — local MCP environment

This backend stores API clients and their authenticated calls to a weather endpoint, along with normalized location lookups and cached weather snapshots to avoid excessive upstream requests. The main workflow is: a client calls the single `weather` tool, the service resolves a location, checks/creates a cache entry, optionally fetches fresh data from the upstream provider, and records the request for auditing and quota enforcement.

Repository: https://github.com/mschneider82/mcp-openweather
Homepage: https://smithery.ai/server/@mschneider82/mcp-openweather

## Datastore

- `api_clients.json` — Represents applications/users authorized to call the Weather Service. Even though the tool surface has no parameters, a production service typically authenticates requests and enforces quotas per client. (12 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_request_quota', 'requests_this_month', 'reset_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_request_quota >= 0
  - constraint: requests_this_month >= 0
  - constraint: requests_this_month <= monthly_request_quota OR plan IN ('enterprise')
- `api_keys.json` — API keys used to authenticate incoming requests to the Weather Service. (12 rows; fields: ['id', 'client_id', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_prefix)
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
- `locations.json` — Normalized location entities resolved from caller context (e.g., IP geolocation) or defaults. The tool surface has no explicit location parameters, so this table supports server-selected locations and caching per resolved coordinate. (20 rows; fields: ['id', 'source', 'display_name', 'country_code', 'latitude', 'longitude', 'timezone', 'created_at', 'updated_at'])
  - constraint: latitude >= -90 AND latitude <= 90
  - constraint: longitude >= -180 AND longitude <= 180
  - constraint: unique(latitude, longitude, source)
- `weather_snapshots.json` — Cached weather payloads fetched from the upstream weather provider (e.g., OpenWeather) for a specific location. Supports TTL-based caching and resilience when upstream is unavailable. (33 rows; fields: ['id', 'location_id', 'provider', 'status', 'observed_at', 'fetched_at', 'expires_at', 'temperature_c', 'humidity_pct', 'wind_speed_mps', 'conditions', 'raw_payload', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'failed']
  - constraint: foreign key (location_id) references locations(id) on delete cascade
  - constraint: humidity_pct IS NULL OR (humidity_pct >= 0 AND humidity_pct <= 100)
  - constraint: expires_at >= fetched_at
  - constraint: unique(location_id, provider, fetched_at)
- `weather_requests.json` — Audit log for every invocation of the `weather` tool. Supports quota enforcement, debugging, and cache hit/miss metrics. (39 rows; fields: ['id', 'client_id', 'api_key_id', 'location_id', 'snapshot_id', 'status', 'cache_status', 'http_status_code', 'error_code', 'error_message', 'upstream_latency_ms', 'total_latency_ms', 'request_ip', 'request_user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['served', 'error', 'rate_limited']
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
  - constraint: http_status_code >= 100 AND http_status_code <= 599
  - constraint: total_latency_ms >= 0
  - constraint: upstream_latency_ms IS NULL OR upstream_latency_ms >= 0

## Business rules enforced by the tools

- Every `weather` tool invocation MUST create exactly one weather_requests row.
- If an API key is presented, it MUST match an api_keys row with status='active' and its client_id MUST match the resolved api_client.
- If api_clients.status != 'active', the request MUST be rejected and logged with weather_requests.status='error' (or 'rate_limited' if suspended due to quota policy) and an appropriate http_status_code (e.g., 403).
- A non-enterprise client MUST NOT exceed monthly_request_quota within the window ending at api_clients.reset_at; when exceeded, the service MUST return rate limiting and log weather_requests.status='rate_limited'.
- For a served request, location_id MUST be set and snapshot_id MUST reference an existing weather_snapshots row.
- A weather_snapshots row is considered usable without refresh only if status='fresh' and expires_at > now(); otherwise the service MUST attempt a refresh and record cache_status as 'stale_refresh' (if served) or set request status='error' if refresh fails and no prior snapshot is acceptable per policy.
- When creating locations, latitude must be in [-90, 90] and longitude in [-180, 180]; attempts to insert out-of-range coordinates MUST fail.
- weather_snapshots.status transitions MUST follow the declared lifecycle transitions; direct transitions that are not listed MUST be rejected by application logic.
- When an upstream fetch fails, the service MUST create or update a weather_snapshots row with status='failed' and record error_message; if a stale snapshot is served as fallback, that served request MUST still reference the snapshot actually returned and log cache_status accordingly.
- All foreign keys referenced in a row MUST exist at write time; deletes MUST respect declared on-delete behavior (restrict for clients/keys, cascade for snapshots tied to locations).