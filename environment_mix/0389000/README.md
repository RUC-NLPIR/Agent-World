# Fetch Server — local MCP environment

Fetch Server is a lightweight HTTP fetching backend that retrieves content from URLs and returns it as HTML, Markdown, plain text, or parsed JSON. The backend stores API clients/keys, individual fetch requests (including headers), and normalized fetch responses with status, timing, and content metadata for auditing, caching, and quota enforcement.

Repository: https://github.com/goswamig/fetch-mcp
Homepage: https://smithery.ai/server/@goswamig/fetch-mcp

## Datastore

- `api_clients.json` — Represents an integrating client (user/team/app) that calls the Fetch Server, used for authentication, rate limits, and auditing. (18 rows; fields: ['id', 'name', 'status', 'default_timeout_ms', 'max_response_bytes', 'daily_request_quota', 'requests_used_today', 'quota_day', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_timeout_ms between 1000 and 120000
  - constraint: max_response_bytes between 1024 and 10485760
  - constraint: daily_request_quota >= 0
- `api_keys.json` — API keys used to authenticate requests to the Fetch Server. Keys belong to an api_client and may be rotated/revoked. (18 rows; fields: ['id', 'api_client_id', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'revoked_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: fk(api_client_id) references api_clients(id) on delete restrict
  - constraint: unique(api_client_id, key_prefix)
  - constraint: unique(key_hash)
  - constraint: revoked_at is null when status = 'active'
- `fetch_requests.json` — An individual fetch operation initiated via one of the tools (fetch_html/markdown/txt/json). Stores the URL, requested format, request headers, and execution status. (19 rows; fields: ['id', 'api_client_id', 'api_key_id', 'tool_name', 'url', 'url_normalized', 'headers', 'status', 'attempt', 'cache_policy', 'cache_key', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_client_id) references api_clients(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: attempt >= 1
  - constraint: url like 'http%://%'
- `fetch_responses.json` — Response data produced by a fetch request, including HTTP metadata and the returned content (raw and/or transformed). One request yields at most one response record. (18 rows; fields: ['id', 'fetch_request_id', 'upstream_status_code', 'upstream_content_type', 'final_url', 'redirect_count', 'response_headers', 'elapsed_ms', 'body_bytes', 'body_truncated', 'content_format', 'content_text', 'content_json', 'parse_error', 'error_type', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `content_format`: ['html', 'markdown', 'text', 'json']
  - constraint: fk(fetch_request_id) references fetch_requests(id) on delete cascade
  - constraint: unique(fetch_request_id)
  - constraint: redirect_count >= 0
  - constraint: elapsed_ms is null or elapsed_ms >= 0
- `host_access_policies.json` — Allow/deny rules per host (or host pattern) used to prevent SSRF, block private networks, and enforce safe fetching behavior. (18 rows; fields: ['id', 'api_client_id', 'host_pattern', 'policy', 'status', 'reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: fk(api_client_id) references api_clients(id) on delete cascade
  - constraint: unique(api_client_id, host_pattern)
  - constraint: host_pattern != ''

## Business rules enforced by the tools

- Each tool call (fetch_html, fetch_markdown, fetch_txt, fetch_json) MUST create exactly one fetch_requests row and at most one fetch_responses row linked by fetch_responses.fetch_request_id.
- Tool parameter url MUST be stored in fetch_requests.url and a canonical form MUST be stored in fetch_requests.url_normalized; cache_key MUST be derived from (url_normalized, tool_name, and a stable hash of headers considered cache-relevant).
- Tool parameter headers (object) MUST be stored in fetch_requests.headers; the system MUST reject headers containing hop-by-hop or dangerous headers (at minimum: Host, Content-Length) and MUST cap total header count and serialized size.
- A request for a client with api_clients.status != 'active' MUST be rejected and MUST NOT transition to running.
- Before executing an upstream request, the service MUST evaluate host_access_policies with precedence: client-scoped active rules override global active rules; deny overrides allow; if no allow rule exists and the server is configured as allowlist-only, the request MUST fail with error_type='blocked'.
- Requests MUST NOT fetch private/internal network destinations (e.g., RFC1918, link-local, localhost) after DNS resolution; violations MUST be recorded as fetch_requests.status='failed' with fetch_responses.error_type='blocked'.
- For each successful authenticated tool call, api_clients.requests_used_today MUST increment by 1 (for the matching quota_day); if requests_used_today would exceed daily_request_quota, the request MUST be rejected or marked failed with error_type='blocked' (quota) and no upstream fetch performed.
- fetch_requests.status transitions MUST follow the defined lifecycle; setting status='succeeded' requires a corresponding fetch_responses row with content_format matching tool_name mapping: fetch_html->html, fetch_markdown->markdown, fetch_txt->text, fetch_json->json.
- For fetch_json, the service MUST attempt to parse upstream body as JSON; on parse failure, fetch_requests.status MUST be 'failed' and fetch_responses.error_type MUST be 'parse_error' with parse_error populated.
- Response body storage MUST respect api_clients.max_response_bytes; if exceeded, fetch_responses.body_truncated MUST be true and body_bytes MUST reflect stored bytes.