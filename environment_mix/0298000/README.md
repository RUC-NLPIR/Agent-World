# Naver Search — local MCP environment

This backend powers an API wrapper around Naver Search endpoints by authenticating callers, validating/normalizing query inputs, enforcing quotas, and recording each search/correction/adult-check request with its response payload. Main workflows are: API key authentication -> request validation (keyword/page/sort/filter constraints per endpoint) -> optional caching of identical requests -> persistence of request + result items for auditing and analytics.

Repository: https://github.com/jikime/py-mcp-naver-search
Homepage: https://smithery.ai/server/@jikime/py-mcp-naver-search

## Datastore

- `api_keys.json` — API keys used by clients of this service. Keys map to Naver credentials/profile, enforce quotas, and are used to attribute request logs. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'name', 'owner', 'status', 'naver_client_id', 'naver_client_secret_ref', 'quota_day_requests', 'quota_day_results_items', 'rate_limit_rps', 'rate_limit_burst', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: quota_day_requests >= 0
  - constraint: quota_day_results_items >= 0
- `request_logs.json` — Immutable log of each tool invocation (search_* / correct_errata / check_adult_query), including normalized parameters, upstream request metadata, and response summary for auditing, caching, and analytics. (38 rows; fields: ['id', 'api_key_id', 'tool_name', 'keyword', 'page', 'display', 'start', 'sort', 'filter', 'normalized_params', 'cache_key', 'cache_hit', 'status', 'upstream_endpoint', 'upstream_http_status', 'error_code', 'error_message', 'response_meta', 'raw_response_ref', 'result_items_count', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'validated', 'upstream_requested', 'succeeded', 'failed']
  - constraint: fk(api_key_id) references api_keys.id
  - constraint: result_items_count >= 0
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: upstream_http_status is null or (upstream_http_status >= 100 and upstream_http_status <= 599)
- `response_cache.json` — Cache of successful upstream responses keyed by canonical request parameters, to reduce upstream calls and latency. Entries are referenced by request_logs.cache_key. (26 rows; fields: ['id', 'cache_key', 'tool_name', 'normalized_params', 'status', 'response_meta', 'raw_response_ref', 'items_ref', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'purged']
  - constraint: unique(cache_key)
  - constraint: expires_at > created_at
- `search_result_items.json` — Normalized per-item results for search_* tools. Stores a common cross-endpoint superset and preserves raw item JSON for endpoint-specific fields. (38 rows; fields: ['id', 'request_id', 'tool_name', 'rank', 'title', 'description', 'link_url', 'thumbnail_url', 'publisher_or_source', 'author', 'pub_date', 'price', 'category', 'address', 'telephone', 'raw_item', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['search_blog', 'search_news', 'search_book', 'search_encyclopedia', 'search_cafe_article', 'search_kin', 'search_local', 'search_shop', 'search_doc', 'search_image', 'search_webkr']
  - constraint: fk(request_id) references request_logs.id on delete cascade
  - constraint: rank >= 1
  - constraint: unique(request_id, rank)
- `usage_counters.json` — Pre-aggregated per-api-key usage for quota and rate-limit enforcement. Updated transactionally when request_logs are created and completed. (19 rows; fields: ['id', 'api_key_id', 'window_start', 'window_type', 'requests_total', 'requests_succeeded', 'requests_failed', 'result_items_total', 'created_at', 'updated_at'])
  - lifecycle `window_type`: ['day']
  - constraint: fk(api_key_id) references api_keys.id on delete cascade
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: requests_total >= 0
  - constraint: requests_succeeded >= 0

## Business rules enforced by the tools

- Every tool invocation MUST create exactly one request_logs row with tool_name set to the invoked tool.
- request_logs.api_key_id MUST reference an api_keys row with status='active'; otherwise the request is rejected and no upstream call is made.
- For search_* tools, request_logs.keyword MUST be non-null and length between 1 and 255 after trimming; for correct_errata and check_adult_query, keyword MUST be non-null and length between 1 and 255.
- Pagination normalization: if page is provided it MUST be >= 1; start MUST be computed as (page-1)*display+1 when upstream requires start; otherwise start may be null.
- Tool-specific parameter constraints are enforced during validation and stored into request_logs.normalized_params: search_news/search_blog/search_cafe_article support sort in {'sim','date'}; search_kin supports sort in {'sim','date','point'}; search_shop supports sort in {'sim','date','asc','dsc'}; search_local supports sort in {'random','comment'} and MUST enforce display<=5 and start<=1 per tool description; search_image supports sort in {'sim','date'} and filter in {'all','large','medium','small'}.
- request_logs.status MUST follow the declared transitions; e.g., it cannot move from failed back to validated, and succeeded/failed are terminal.
- On completion of a request, request_logs.result_items_count MUST equal the number of associated search_result_items rows (0 for non-search tools).
- Caching: a successful response MAY be written to response_cache with status='fresh' and expires_at set; subsequent identical normalized requests SHOULD set request_logs.cache_hit=true and avoid upstream calls while the cache entry is fresh and unexpired.
- Quota enforcement: for each api_key_id and UTC day window, usage_counters.requests_total MUST NOT exceed api_keys.quota_day_requests; and usage_counters.result_items_total MUST NOT exceed api_keys.quota_day_results_items. If a call would exceed quota, it MUST be rejected before upstream call and logged as failed with an error_code indicating quota exceeded.
- FK integrity: deleting an api_keys row MUST cascade-delete usage_counters rows; deleting a request_logs row MUST cascade-delete search_result_items rows; response_cache rows are independent and are purged by TTL.