# United States Weather — local MCP environment

This backend stores normalized US geolocations, nearby weather stations, ingested NWS-style weather products (current conditions, forecasts, alerts), and an audit trail of API requests. Main workflows: resolve a user-provided location (lat,lng or state code) into an internal location record, then read the latest cached products (or refresh them asynchronously) and return them; also support station lookup by distance and local time by timezone at location.

Repository: https://github.com/smithery-ai/mcp-servers
Homepage: https://smithery.ai/server/@smithery-ai/national-weather-service

## Datastore

- `locations.json` — Canonical geospatial locations within US coverage (states, territories, coastal waters) derived from user coordinate inputs or state/territory codes. Used to attach timezone, admin areas, and to key cached weather products. (18 rows; fields: ['id', 'source', 'input_location_raw', 'latitude', 'longitude', 'state_code', 'timezone', 'coverage_type', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'blocked']
  - constraint: required(input_location_raw)
  - constraint: ((latitude IS NOT NULL AND longitude IS NOT NULL) OR state_code IS NOT NULL)
  - constraint: latitude BETWEEN -90 AND 90
  - constraint: longitude BETWEEN -180 AND 180
- `stations.json` — Weather observation stations (ASOS/AWOS/etc.) used for nearby-station discovery and as sources for current conditions. (18 rows; fields: ['id', 'station_code', 'name', 'station_type', 'latitude', 'longitude', 'elevation_m', 'state_code', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'retired']
  - constraint: unique(station_code)
  - constraint: latitude BETWEEN -90 AND 90
  - constraint: longitude BETWEEN -180 AND 180
  - constraint: elevation_m IS NULL OR elevation_m BETWEEN -500 AND 9000
- `weather_products.json` — Cached weather data products keyed by location and product kind, including current conditions, daily forecast, hourly forecast, and active alerts. Stores the normalized payload plus provenance and freshness/expiry for efficient reads. (18 rows; fields: ['id', 'location_id', 'kind', 'variant', 'provider', 'provider_ref', 'issued_at', 'valid_from', 'valid_to', 'fetched_at', 'expires_at', 'payload', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'expired', 'error']
  - constraint: fk(location_id) references locations(id) on delete cascade
  - constraint: unique(location_id, kind, variant)
  - constraint: fetched_at <= now()
  - constraint: expires_at IS NULL OR expires_at >= fetched_at
- `alerts.json` — Denormalized active alert instances (warnings/watches/advisories) with severity and geographies, to support fast severity filtering and state-code queries without parsing large product payloads. (18 rows; fields: ['id', 'provider', 'provider_alert_id', 'severity', 'event', 'headline', 'description', 'instruction', 'effective_at', 'expires_at', 'status', 'area_state_codes', 'area_geocode', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'ended', 'cancelled']
  - constraint: unique(provider, provider_alert_id)
  - constraint: expires_at IS NULL OR effective_at IS NULL OR expires_at >= effective_at
  - constraint: array_length(area_state_codes) >= 0
- `api_requests.json` — Audit log of tool calls for observability, rate limiting, and debugging. Each tool invocation stores the normalized request and summary of the response. (19 rows; fields: ['id', 'tool_name', 'location_raw', 'location_id', 'days', 'hours', 'limit', 'severity', 'response_status_code', 'cache_hit', 'served_weather_product_id', 'latency_ms', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'rejected']
  - constraint: fk(location_id) references locations(id)
  - constraint: fk(served_weather_product_id) references weather_products(id)
  - constraint: days IS NULL OR (days >= 1 AND days <= 7)
  - constraint: hours IS NULL OR (hours >= 1 AND hours <= 48)

## Business rules enforced by the tools

- Location parsing: for tools requiring coordinates, location must match '^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$' and be within US boundaries (including territories and coastal waters) before creating/using a locations row.
- For get_weather_alerts, location may be either coordinates or a 2-letter state/territory code from the allowed set; if state code is provided, queries must use alerts.area_state_codes containment to filter active alerts.
- get_weather_forecast must clamp/validate days to integer range 1..7; get_hourly_forecast must clamp/validate hours to integer range 1..48; find_weather_stations must clamp/validate limit to integer range 1..20.
- Cache selection: for current/forecast/alerts, the service should serve the newest weather_products row for (location_id, kind, variant) with status='fresh' and expires_at>now(); otherwise it may serve status='stale' and asynchronously refresh, but must not serve status='error' unless no other record exists.
- Variant mapping: daily forecast uses variant 'days=N'; hourly uses 'hours=N'; alerts uses 'severity=X' where X is one of all/extreme/severe/moderate/minor; current typically uses NULL variant.
- When ingesting provider alert feeds, upsert alerts by (provider, provider_alert_id); if provider indicates alert ended/cancelled or expires_at<=now(), transition status from active to ended/cancelled and do not allow transitions back to active for the same provider_alert_id.
- find_weather_stations must return only stations.status='active' ordered by computed haversine distance from the input coordinates; distance is computed at query-time and not persisted.
- get_local_time must return timezone-adjusted now() for the resolved location; locations.timezone must be present, otherwise the request is failed with a resolvable-location error and logged in api_requests.
- All tool invocations must create an api_requests row with tool_name, location_raw, validated parameters, and final status; failed validation results in status='rejected' with response_status_code in the 4xx range.