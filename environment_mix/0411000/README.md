# Naver Maps Directions Server — local MCP environment

This backend stores authenticated usage of Naver Maps APIs for directions, geocoding, reverse geocoding, and static map rendering. The main workflows are: clients authenticate with an API key, submit a request (route/geocode/reverse/static map), the service calls Naver upstream, stores request/response metadata for auditing/billing/debugging, and enforces per-key quotas and rate limits.

Repository: https://github.com/Chaeyun06/naver-maps-mcp
Homepage: https://smithery.ai/server/@Chaeyun06/naver-maps-mcp

## Datastore

- `api_keys.json` — Represents client credentials used to access this MCP server. Tracks ownership, status, and quota/rate-limit configuration for each key. (32 rows; fields: ['id', 'key_prefix', 'key_hash', 'owner_type', 'owner_id', 'name', 'status', 'quota_daily_requests', 'quota_monthly_requests', 'rate_limit_rps', 'rate_limit_burst', 'allowed_endpoints', 'last_used_at', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_prefix)
  - constraint: quota_daily_requests >= 0
  - constraint: quota_monthly_requests >= 0
  - constraint: rate_limit_rps > 0
- `naver_credentials.json` — Stores the upstream Naver API credentials/config used by this server (e.g., NCP API key/secret), including rotation and activation state. Requests reference the active credential used for traceability. (12 rows; fields: ['id', 'provider', 'name', 'client_id', 'client_secret_enc', 'status', 'scopes', 'created_at', 'updated_at', 'retired_at'])
  - lifecycle `status`: ['active', 'inactive', 'retired']
  - constraint: unique(provider, name)
  - constraint: status in ('active','inactive','retired')
  - constraint: scopes length >= 1
- `map_requests.json` — Canonical log of all tool calls (directions/geocode/reverse/static map). Stores normalized inputs, response metadata, and links to request/response payload records for debugging and analytics. (36 rows; fields: ['id', 'api_key_id', 'naver_credential_id', 'tool_name', 'idempotency_key', 'status', 'cache_key', 'client_ip', 'user_agent', 'request_params', 'normalized_params', 'upstream_endpoint', 'upstream_status_code', 'upstream_error_code', 'duration_ms', 'response_size_bytes', 'cost_units', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'queued', 'calling_upstream', 'succeeded', 'failed', 'rejected', 'cached']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: foreign key (naver_credential_id) references naver_credentials(id)
  - constraint: cost_units >= 0
  - constraint: duration_ms is null or duration_ms >= 0
- `map_responses.json` — Stores response payloads for requests. For static map, stores base64 data URI (or a pointer to object storage). For other tools, stores JSON response from upstream. (15 rows; fields: ['id', 'request_id', 'content_type', 'payload_json', 'payload_text', 'image_data_uri', 'blob_object_key', 'sha256', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `content_type`: ['application/json', 'image/png', 'image/jpeg', 'text/plain']
  - constraint: foreign key (request_id) references map_requests(id) on delete cascade
  - constraint: unique(request_id)
  - constraint: exactly one of (payload_json, payload_text, image_data_uri, blob_object_key) must be non-null
  - constraint: image_data_uri is not null implies content_type in ('image/png','image/jpeg')
- `usage_counters.json` — Aggregated per-API-key usage for quota enforcement. Updated transactionally when a request is accepted and/or completed depending on billing policy. (30 rows; fields: ['id', 'api_key_id', 'period_type', 'period_start', 'tool_name', 'request_count', 'cost_units', 'last_request_at', 'created_at', 'updated_at'])
  - lifecycle `period_type`: ['day', 'month']
  - constraint: foreign key (api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, period_type, period_start, tool_name)
  - constraint: request_count >= 0
  - constraint: cost_units >= 0

## Business rules enforced by the tools

- Every tool invocation (naver_directions, naver_geocode, naver_reverse_geocode, naver_static_map) MUST create exactly one map_requests row with tool_name set accordingly and request_params containing the received JSON payload (which may be empty).
- A map_requests row MUST reference a valid api_keys row; requests with api_keys.status != 'active' MUST be rejected with map_requests.status = 'rejected' and MUST NOT increment usage_counters.
- If idempotency_key is provided, the service MUST return the first successful response for the tuple (api_key_id, tool_name, idempotency_key) and MUST NOT create additional billable usage for duplicates.
- For accepted requests, the service MUST enforce rate limits (rate_limit_rps, rate_limit_burst) and quotas (quota_daily_requests, quota_monthly_requests). If a quota would be exceeded, the request MUST be rejected and MUST NOT call upstream.
- When a request is sent to Naver upstream, map_requests.status MUST transition to 'calling_upstream' and map_requests.naver_credential_id MUST reference an 'active' naver_credentials record that includes the required scope for the tool.
- On completion, map_requests.status MUST become 'succeeded' or 'failed'. A succeeded request MUST have a corresponding map_responses row (unique per request_id).
- map_responses MUST store exactly one payload form: payload_json for JSON tools, or image_data_uri/blob_object_key for static map images. Storing both JSON and image content for the same request is forbidden.
- usage_counters MUST be incremented transactionally when a request becomes billable (either at accept-time or success-time by policy), and the increment MUST align with map_requests.cost_units.
- Caching: if a response is served from cache, map_requests.status MAY be 'cached' and upstream fields (naver_credential_id, upstream_status_code) SHOULD be null; cached responses MUST still be linked via map_responses and MAY be configured as non-billable (cost_units = 0) depending on policy.
- Retention: map_responses.expires_at, when set, MUST be enforced by a background job that deletes/archives payloads after expiration while preserving map_requests metadata for audit.