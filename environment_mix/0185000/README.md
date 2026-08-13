# Fetch MCP Server — local MCP environment

This backend powers a lightweight web-fetching API that retrieves remote URLs and returns the response transformed into HTML, Markdown, plain text, or parsed JSON. It stores callers (API keys), each fetch request with its parameters, the upstream HTTP response metadata, and the produced output segments to support truncation (max_length/start_index), auditing, rate limits, and caching/deduplication.

Repository: https://github.com/zcaceres/fetch-mcp
Homepage: https://smithery.ai/server/fetch-mcp

## Datastore

- `api_keys.json` — Represents an authenticated caller of the Fetch MCP Server and stores quota/rate limit configuration. (26 rows; fields: ['id', 'key_hash', 'name', 'status', 'rate_limit_rpm', 'monthly_request_quota', 'monthly_byte_quota', 'notes', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(name)
  - constraint: rate_limit_rpm >= 1 and rate_limit_rpm <= 6000
  - constraint: monthly_request_quota is null or monthly_request_quota >= 0
- `fetch_requests.json` — One record per tool invocation (fetch_html/fetch_markdown/fetch_txt/fetch_json) including parameters, normalization, and execution status. (35 rows; fields: ['id', 'api_key_id', 'tool_name', 'url', 'normalized_url', 'headers', 'max_length', 'start_index', 'status', 'requested_at', 'started_at', 'finished_at', 'error_code', 'error_message', 'cache_policy', 'cache_hit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: max_length >= 1 and max_length <= 200000
  - constraint: start_index >= 0
  - constraint: start_index <= 100000000
- `http_responses.json` — Stores the raw upstream HTTP response metadata and (optionally) body for a fetch. Used for caching, auditing, and conversion to output formats. (37 rows; fields: ['id', 'fetch_request_id', 'final_url', 'redirect_count', 'status_code', 'response_headers', 'content_type', 'charset', 'body_bytes', 'body_storage', 'body_inline', 'body_blob_ref', 'sha256', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `body_storage`: ['inline', 'blob_ref', 'none']
  - constraint: fk(fetch_request_id) references fetch_requests(id) on delete cascade
  - constraint: unique(fetch_request_id)
  - constraint: redirect_count >= 0 and redirect_count <= 20
  - constraint: status_code >= 100 and status_code <= 599
- `fetch_outputs.json` — Stores the produced output for a request in the requested format (HTML/Markdown/TXT/JSON). Supports slicing via start_index/max_length while still caching the full converted output when feasible. (35 rows; fields: ['id', 'fetch_request_id', 'format', 'full_length_chars', 'start_index', 'max_length', 'returned_length_chars', 'content_storage', 'content_inline', 'content_blob_ref', 'json_value', 'parse_warnings', 'created_at', 'updated_at'])
  - lifecycle `content_storage`: ['inline', 'blob_ref', 'none']
  - constraint: fk(fetch_request_id) references fetch_requests(id) on delete cascade
  - constraint: unique(fetch_request_id)
  - constraint: full_length_chars >= 0
  - constraint: start_index >= 0
- `usage_events.json` — Append-only metering events for rate limiting, quotas, and operational analytics (bytes fetched, bytes returned, cache hits, errors). (31 rows; fields: ['id', 'api_key_id', 'fetch_request_id', 'event_type', 'tool_name', 'http_status_code', 'upstream_body_bytes', 'returned_chars', 'cache_hit', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['request_accepted', 'upstream_fetched', 'response_returned', 'request_failed']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(fetch_request_id) references fetch_requests(id) on delete cascade
  - constraint: upstream_body_bytes is null or upstream_body_bytes >= 0
  - constraint: returned_chars is null or returned_chars >= 0

## Business rules enforced by the tools

- Each tool call (fetch_html/fetch_markdown/fetch_txt/fetch_json) creates exactly one fetch_requests row with tool_name set accordingly, url/headers/max_length/start_index persisted as provided (with defaults applied when omitted).
- max_length defaults to 5000 and start_index defaults to 0 when not provided; stored values must satisfy max_length in [1, 200000] and start_index >= 0.
- Requests must be rejected if the associated api_keys.status is not 'active'.
- Rate limiting: for each api_key_id, the count of usage_events where event_type='request_accepted' within the last 60 seconds must be <= api_keys.rate_limit_rpm; otherwise the request is rejected and no fetch_requests row is created.
- Monthly quotas: if api_keys.monthly_request_quota is not null, the count of usage_events(event_type='request_accepted') in the current calendar month must be < monthly_request_quota before accepting a new request; similarly, if monthly_byte_quota is not null, the sum of usage_events.returned_chars (or returned bytes computed by encoding) for event_type='response_returned' in the month must be < monthly_byte_quota.
- For a succeeded fetch_requests row, an http_responses row must exist (unique by fetch_request_id) and a fetch_outputs row must exist (unique by fetch_request_id).
- Format mapping: tool_name='fetch_html' => fetch_outputs.format='html'; 'fetch_markdown' => 'markdown'; 'fetch_txt' => 'text'; 'fetch_json' => 'json'.
- Slicing behavior: fetch_outputs.content_inline (or json serialized string where applicable) must equal the full converted output substring from start_index to start_index+max_length, clamped to [0, full_length_chars]. returned_length_chars must match the stored substring length.
- Caching behavior: when cache_policy='use_cache', the service may reuse an existing http_responses body identified by (normalized_url, sha256) within a TTL (implemented outside these tables); if reused, fetch_requests.cache_hit must be true and http_responses.fetched_at may reflect original fetch time while fetch_requests.requested_at reflects current call.
- Headers are stored as provided but the implementation must strip or overwrite hop-by-hop and dangerous headers (e.g., Host, Connection, Content-Length) before sending upstream; the sanitized version is what must be persisted in fetch_requests.headers.
- If tool_name='fetch_json' and the upstream body is not valid JSON, fetch_requests.status must transition to 'failed' with error_code='invalid_json', and usage_events must include a 'request_failed' event referencing the request.