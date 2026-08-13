# Weather — local MCP environment

This backend stores normalized weather alert and forecast data sourced from an upstream provider, plus the request/audit trail used to serve the public API. Main workflows are: ingest/update alerts by state, ingest/update forecast grids by lat/lon, and answer read requests by looking up the latest active alerts and most recent forecast for the nearest supported grid point.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@turkyden/weather

## Datastore

- `api_clients.json` — Represents API consumers (internal service principals or external clients) used for rate limiting, auditing, and abuse prevention. (18 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'quota_requests_per_minute', 'quota_requests_per_day', 'created_at', 'updated_at', 'last_seen_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: quota_requests_per_minute >= 0
  - constraint: quota_requests_per_day >= 0
- `request_logs.json` — Immutable audit log of API calls to support debugging, analytics, and quota enforcement for get-alerts and get-forecast. (18 rows; fields: ['id', 'api_client_id', 'tool_name', 'params', 'state', 'latitude', 'longitude', 'response_status_code', 'served_from_cache', 'latency_ms', 'error_code', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['get-alerts', 'get-forecast']
  - constraint: state is not null iff tool_name = 'get-alerts'
  - constraint: latitude is not null and longitude is not null iff tool_name = 'get-forecast'
  - constraint: length(state) = 2 when state is not null
  - constraint: latitude between -90 and 90 when latitude is not null
- `weather_alerts.json` — Stores weather alert events (e.g., warnings, watches, advisories) keyed by upstream alert id and normalized for fast lookup by state and validity window. (17 rows; fields: ['id', 'upstream_provider', 'upstream_alert_id', 'state', 'event', 'severity', 'urgency', 'certainty', 'headline', 'description_text', 'effective_at', 'expires_at', 'status', 'ingested_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'cancelled']
  - constraint: unique(upstream_provider, upstream_alert_id)
  - constraint: length(state) = 2
  - constraint: effective_at <= expires_at when both are not null
- `forecast_points.json` — Canonical forecast grid points (or nearest-point mapping targets) used to serve get-forecast by lat/lon efficiently and consistently. (18 rows; fields: ['id', 'upstream_provider', 'grid_id', 'grid_x', 'grid_y', 'latitude', 'longitude', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(upstream_provider, grid_id, grid_x, grid_y)
  - constraint: latitude between -90 and 90
  - constraint: longitude between -180 and 180
  - constraint: grid_x >= 0
- `forecasts.json` — Forecast payloads for forecast_points, versioned by issuance time. get-forecast returns the most recent successful forecast for the nearest active point. (19 rows; fields: ['id', 'forecast_point_id', 'issued_at', 'valid_from', 'valid_to', 'status', 'periods', 'raw_payload', 'ingested_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'superseded', 'failed']
  - constraint: foreign key(forecast_point_id) references forecast_points(id) on delete restrict
  - constraint: unique(forecast_point_id, issued_at)
  - constraint: valid_from <= valid_to when both are not null
  - constraint: periods is non-empty when status = 'available'

## Business rules enforced by the tools

- get-alerts(state) must validate state as exactly 2 characters and uppercase it before lookup; it returns only weather_alerts where state matches and status='active', additionally filtering out rows with expires_at < now() when expires_at is not null (and transitioning such rows to status='expired' asynchronously).
- get-forecast(latitude, longitude) must validate latitude in [-90, 90] and longitude in [-180, 180], then select the nearest forecast_points row with status='active' (by geospatial distance); it returns the latest forecasts row for that point where status='available' ordered by issued_at desc.
- When a new forecasts record with (forecast_point_id, issued_at) is inserted as status='available', any prior forecasts for the same forecast_point_id with issued_at < new.issued_at must be transitioned to status='superseded'.
- API clients with status!='active' must not be allowed to consume the tools; request_logs must still record the attempt with an appropriate response_status_code (e.g., 401/403) and error_code.
- Quota enforcement: for each api_client_id, the number of request_logs in the last rolling minute must be <= quota_requests_per_minute and in the last UTC day must be <= quota_requests_per_day; if exceeded, the request must be rejected and logged.
- All foreign keys must be enforced: request_logs.api_client_id must reference api_clients.id when non-null; forecasts.forecast_point_id must reference forecast_points.id.
- Ingestion must be idempotent for alerts: (upstream_provider, upstream_alert_id) is unique; updates must only mutate the existing weather_alerts row and adjust status according to upstream cancellation/expiration signals and expires_at.
- Data retention: request_logs older than the configured retention window may be deleted/archived without impacting get-alerts or get-forecast correctness.