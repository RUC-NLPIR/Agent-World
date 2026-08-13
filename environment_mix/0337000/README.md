# Serper Google Search Server — local MCP environment

This backend stores API consumers, their credentials, and an audit trail of Google search requests executed through the Serper-powered search proxy. The primary workflow is: authenticate an API key, record a search request, call the upstream Serper/Google search provider, store the response and usage metrics, and enforce per-key rate limits/quotas.

Repository: https://github.com/garylab/serper-mcp-server
Homepage: https://smithery.ai/server/@garylab/serper-mcp-server

## Datastore

- `api_keys.json` — API credentials used by clients to access the Serper Google Search Server, including quota/rate-limit configuration and key lifecycle. (18 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'owner_type', 'owner_id', 'status', 'quota_requests_per_day', 'rate_limit_per_minute', 'allow_empty_query', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, owner_id)
  - constraint: quota_requests_per_day >= 0
  - constraint: rate_limit_per_minute >= 0
- `search_requests.json` — An audited record of each google_search invocation, including inferred/derived query context, upstream request metadata, and lifecycle state. (17 rows; fields: ['id', 'api_key_id', 'status', 'tool_name', 'input_params', 'query_text', 'locale', 'country', 'safe_search', 'upstream_provider', 'upstream_request_id', 'http_status', 'error_code', 'error_message', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'rejected']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: tool_name = 'google_search'
  - constraint: upstream_provider = 'serper'
  - constraint: http_status between 100 and 599 when not null
- `search_results.json` — Materialized search response payloads and parsed top-level fields for fast retrieval/analytics. Kept separate from requests to allow pruning or partial retention. (19 rows; fields: ['id', 'request_id', 'result_format', 'raw_payload', 'top_result_count', 'has_answer_box', 'created_at', 'updated_at'])
  - lifecycle `result_format`: ['json']
  - constraint: foreign key (request_id) references search_requests(id) on delete cascade
  - constraint: unique(request_id)
  - constraint: top_result_count >= 0 when not null
- `rate_limit_counters.json` — Per-API-key rolling counters used to enforce rate limits and daily quotas without scanning the request table. (16 rows; fields: ['id', 'api_key_id', 'window_type', 'window_start', 'request_count', 'success_count', 'rejected_count', 'created_at', 'updated_at'])
  - lifecycle `window_type`: ['minute', 'day']
  - constraint: foreign key (api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: request_count >= 0
  - constraint: success_count >= 0

## Business rules enforced by the tools

- Each google_search invocation must create exactly one search_requests row with tool_name='google_search' and input_params matching the received JSON object (empty object is valid).
- A request must not transition from a terminal state (succeeded/failed/rejected) to any other state.
- If api_keys.status != 'active', the request must be recorded as status='rejected' with http_status=401 or 403, and no upstream call is made.
- Rate limiting: for a given api_key_id, if rate_limit_per_minute > 0 then the service must reject the request when the minute window request_count would exceed rate_limit_per_minute.
- Daily quota: for a given api_key_id, if quota_requests_per_day > 0 then the service must reject the request when the day window success_count would exceed quota_requests_per_day; only succeeded upstream calls increment success_count.
- For any request that reaches status='succeeded', there must exist exactly one search_results row referencing it; for failed or rejected requests, a search_results row must not be created.
- Deletion policy: deleting an api_key must cascade-delete rate_limit_counters and may retain or purge search_requests/search_results based on compliance configuration; if retained, api_key_id must be replaced by a tombstone key or the delete must be blocked (FK integrity enforced).
- All stored upstream payloads in search_results.raw_payload must be redacted for secrets (e.g., provider keys) and must not contain the raw client API key.