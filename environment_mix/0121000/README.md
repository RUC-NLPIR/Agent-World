# Google Analytics Data API Server — local MCP environment

This backend stores the configuration and operational telemetry for a server that proxies/serves Google Analytics Data API requests, specifically "report" and "realtime" retrieval. It tracks GA4 properties connected to the server, credentials used to call Google APIs, and an audit log of report/realtime requests and their cached responses for observability, cost control, and debugging.

Repository: https://github.com/eno-graph/mcp-server-google-analytics
Homepage: https://smithery.ai/server/@eno-graph/mcp-server-google-analytics

## Datastore

- `ga_properties.json` — GA4 properties configured in this server (each property corresponds to a GA4 propertyId the Google Analytics Data API can query). Used to scope credentials, caching, and request history. (12 rows; fields: ['id', 'property_id', 'display_name', 'time_zone', 'currency_code', 'status', 'default_cache_ttl_seconds', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(property_id) where status != 'deleted'
  - constraint: default_cache_ttl_seconds >= 0
  - constraint: default_cache_ttl_seconds <= 86400
- `google_credentials.json` — Google API credentials used by the server to call the Google Analytics Data API. Supports service accounts and OAuth refresh-token based access. Credentials can be rotated and scoped per GA property. (12 rows; fields: ['id', 'ga_property_id', 'credential_type', 'client_email', 'project_id', 'secret_ref', 'scopes', 'status', 'last_validated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'rotating', 'revoked']
  - constraint: foreign key (ga_property_id) references ga_properties(id)
  - constraint: scopes length >= 1
  - constraint: unique(ga_property_id, client_email) where credential_type = 'service_account_json' and status != 'revoked'
- `ga_requests.json` — Audit log of requests made through the server for both report and realtime endpoints. Stores normalized request metadata plus the raw request/response payload hashes for caching and debugging. (48 rows; fields: ['id', 'request_type', 'ga_property_id', 'credential_id', 'status', 'request_payload', 'request_fingerprint', 'response_payload', 'response_row_count', 'error_code', 'error_message', 'started_at', 'finished_at', 'cache_hit', 'cache_expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (ga_property_id) references ga_properties(id)
  - constraint: foreign key (credential_id) references google_credentials(id)
  - constraint: unique(request_fingerprint) where status in ('queued','running')
  - constraint: response_row_count is null or response_row_count >= 0
- `api_keys.json` — API keys used by clients (including MCP clients) to call this server. Provides authentication, rate limits, and request attribution. (12 rows; fields: ['id', 'key_prefix', 'key_hash', 'label', 'status', 'rate_limit_per_minute', 'daily_quota_requests', 'allowed_property_ids', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix) where status != 'revoked'
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
  - constraint: daily_quota_requests >= 1 and daily_quota_requests <= 1000000
- `api_usage_counters.json` — Aggregated usage counters for rate limiting and quota enforcement per API key. Updated on each request. (29 rows; fields: ['id', 'api_key_id', 'window_start', 'window_type', 'request_count', 'report_count', 'realtime_count', 'created_at', 'updated_at'])
  - lifecycle `window_type`: ['minute', 'day']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: request_count >= 0
  - constraint: report_count >= 0

## Business rules enforced by the tools

- get_report creates a ga_requests row with request_type='report' and request_payload={} (given current tool surface has no parameters), then executes against Google Analytics Data API using an active google_credentials record allowed for the target ga_properties row.
- get_realtime_data creates a ga_requests row with request_type='realtime' and request_payload={} and executes similarly, storing response_payload on success.
- A request must reference an existing ga_properties row whose status='active'; otherwise it must be rejected and a ga_requests row may be created with status='failed' and error_code='PROPERTY_DISABLED_OR_MISSING'.
- Credential selection must only consider google_credentials.status='active' and matching ga_property_id; revoked credentials must never be used.
- If an API key is required by deployment configuration, the presented key must match api_keys.key_hash and api_keys.status='active'; otherwise reject with an auth error and do not call Google APIs.
- When api_keys.allowed_property_ids is non-null and non-empty, requests for any ga_property_id not in that list must be rejected.
- Rate limiting: for each incoming request, increment (or create) the api_usage_counters minute window; if request_count would exceed api_keys.rate_limit_per_minute, reject before calling Google APIs.
- Daily quota: similarly increment (or create) the day window; if request_count would exceed api_keys.daily_quota_requests, reject before calling Google APIs.
- Caching: if there exists a ga_requests row with the same request_fingerprint, status='succeeded', cache_expires_at > now(), it may be served as a cache hit without calling Google APIs; the served request must still be logged with cache_hit=true.
- ga_requests.status transitions must follow the declared lifecycle; e.g., a succeeded request cannot later move to failed.