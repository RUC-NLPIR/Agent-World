# Weather MCP Server — local MCP environment

This backend supports a Weather MCP server that resolves city names to geolocations, fetches and caches hourly weather observations/forecasts for those locations, and records tool invocations for auditing and rate-limiting. Primary workflows are: (1) normalize/resolve an English city name to a canonical location, (2) serve current weather or a date-range of weather from cached hourly data (refreshing via provider when stale/missing), and (3) return the current datetime for an IANA timezone while logging usage.

Repository: https://github.com/isdaniel/mcp_weather_server
Homepage: https://smithery.ai/server/@isdaniel/mcp_weather_server

## Datastore

- `api_clients.json` — Identifies calling clients (apps/users) and their rate limits. Used to attribute tool invocations and enforce quotas. (18 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'rate_limit_per_minute', 'daily_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: rate_limit_per_minute between 1 and 6000
  - constraint: daily_quota between 1 and 1000000
- `locations.json` — Canonical city/location records resolved from an English city name to latitude/longitude and a timezone. Used as the anchor for weather timeseries caching. (18 rows; fields: ['id', 'english_city_name', 'country_code', 'admin_region', 'latitude', 'longitude', 'timezone_name', 'resolution_status', 'provider', 'provider_location_ref', 'created_at', 'updated_at'])
  - lifecycle `resolution_status`: ['resolved', 'ambiguous', 'failed']
  - constraint: english_city_name not empty
  - constraint: latitude between -90 and 90
  - constraint: longitude between -180 and 180
  - constraint: timezone_name matches IANA format when not null
- `weather_hourly.json` — Hourly weather data points (observations/forecast) for a location, used to answer current weather and date-range queries. Stored in a normalized form including temperature and weather code. (17 rows; fields: ['id', 'location_id', 'hour_start_utc', 'temperature_c', 'weather_code', 'weather_description', 'data_kind', 'source_provider', 'ingest_status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `ingest_status`: ['fresh', 'stale', 'superseded']
  - constraint: fk(location_id) references locations(id) on delete cascade
  - constraint: unique(location_id, hour_start_utc, source_provider)
  - constraint: temperature_c between -100 and 70
  - constraint: weather_code between 0 and 999
- `timezone_clock_cache.json` — Lightweight cache for timezone validity/offset metadata to support current datetime lookups and avoid repeated timezone parsing/validation cost. (18 rows; fields: ['id', 'timezone_name', 'is_valid', 'last_offset_minutes', 'last_computed_at', 'created_at', 'updated_at'])
  - lifecycle `is_valid`: ['true', 'false']
  - constraint: unique(timezone_name)
  - constraint: timezone_name not empty
  - constraint: last_offset_minutes between -840 and 840 when not null
- `tool_invocations.json` — Audit log of MCP tool calls, including inputs and outputs metadata. Supports billing/quota enforcement and debugging. (19 rows; fields: ['id', 'client_id', 'tool_name', 'city', 'start_date', 'end_date', 'timezone_name', 'resolved_location_id', 'request_status', 'error_code', 'error_message', 'response_summary', 'provider_calls', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `request_status`: ['received', 'validated', 'running', 'succeeded', 'failed']
  - constraint: fk(client_id) references api_clients(id)
  - constraint: fk(resolved_location_id) references locations(id)
  - constraint: provider_calls >= 0
  - constraint: duration_ms >= 0 when not null

## Business rules enforced by the tools

- Every tool invocation must create a tool_invocations row with request_status='received' and transition through valid statuses only; it must end in 'succeeded' or 'failed'.
- api_clients.status must be 'active' to execute any tool; otherwise the invocation must fail with error_code='CLIENT_NOT_ACTIVE'.
- Rate limiting: for each client_id, the count of tool_invocations created in the last 60 seconds must not exceed api_clients.rate_limit_per_minute; if exceeded, fail with error_code='RATE_LIMITED'.
- Daily quota: for each client_id, the count of tool_invocations with created_at in the current UTC day must not exceed api_clients.daily_quota; if exceeded, fail with error_code='DAILY_QUOTA_EXCEEDED'.
- City input to weather tools must be treated as English; the service must normalize (trim, collapse whitespace, title-case) before lookup/insert into locations. Non-English names must be translated before reaching the DB (enforced at the tool layer).
- To fulfill get_current_weather(city): resolve (or create) a locations row with resolution_status='resolved'; then return the weather_hourly row for the current UTC hour for that location. If missing or stale (fetched_at older than 15 minutes for observed hours or older than 2 hours for forecast hours), fetch from provider and upsert weather_hourly (marking prior rows for same hour/provider as 'superseded' if overwritten).
- To fulfill get_weather_by_datetime_range(city,start_date,end_date): start_date must be <= end_date and the range length must be <= 31 days; otherwise fail with error_code='INVALID_DATE_RANGE'. The service must return all weather_hourly rows with hour_start_utc between start_dateT00:00:00Z (inclusive) and (end_date+1)T00:00:00Z (exclusive) for the resolved location, fetching/upserting missing hours as needed.
- weather_hourly must be unique per (location_id, hour_start_utc, source_provider); ingestion updates must preserve uniqueness by updating the existing row or superseding prior versions.
- To fulfill get_current_datetime(timezone_name): timezone_name must be a valid IANA identifier or 'UTC'; the service should upsert timezone_clock_cache for timezone_name with is_valid accordingly. If invalid, fail with error_code='INVALID_TIMEZONE'.
- FK integrity: deleting a locations row must cascade-delete its weather_hourly rows; tool_invocations.resolved_location_id must be set to null or prevented from referencing deleted locations (implementation chooses restrict or set null; schema assumes nullable FK).