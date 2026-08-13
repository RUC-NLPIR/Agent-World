# Bilibili API Server — local MCP environment

This backend powers an API server that proxies Bilibili search and danmaku endpoints while adding caching, normalization (precise filtering), and operational controls. It stores API clients (keys), search queries with typed results (user/video/live/article), and danmaku fetch jobs plus cached danmaku payloads keyed by BV id.

Repository: https://github.com/chenmingkong/bilibili-mcp-server
Homepage: https://smithery.ai/server/@chenmingkong/bilibili-mcp-server

## Datastore

- `api_clients.json` — Represents calling applications/clients of this MCP server. Used for authentication, rate limiting, and auditing of requests across all tools. (12 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'quota_per_minute', 'quota_per_day', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: quota_per_minute >= 1 AND quota_per_minute <= 6000
  - constraint: quota_per_day >= 1 AND quota_per_day <= 1000000
- `search_queries.json` — Stores search requests made through the server (general_search, search_user, get_precise_results) including keyword, type, pagination, and response caching metadata. (19 rows; fields: ['id', 'client_id', 'tool_name', 'keyword', 'search_type', 'page', 'status', 'error_code', 'error_message', 'upstream_cache_key', 'cache_hit', 'expires_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
  - constraint: page >= 1 AND page <= 1000
  - constraint: length(trim(keyword)) >= 1 AND length(keyword) <= 200
  - constraint: unique(client_id, upstream_cache_key, created_at::date)  -- soft dedupe per day to avoid runaway duplicates
- `search_results.json` — Stores normalized items returned by Bilibili search. Used to serve cached responses and to compute 'precise' (exact match) results by filtering/flagging. (18 rows; fields: ['id', 'query_id', 'result_type', 'rank', 'title', 'exact_match', 'external_id', 'bv_id', 'author_name', 'url', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `result_type`: ['user', 'video', 'live', 'article']
  - constraint: foreign key (query_id) references search_queries(id) on delete cascade
  - constraint: rank >= 1 AND rank <= 500
  - constraint: unique(query_id, rank)
  - constraint: unique(query_id, result_type, external_id)
- `danmaku_requests.json` — Tracks calls to get_video_danmaku and manages caching/retries. Stores request state and links to the cached danmaku payload. (18 rows; fields: ['id', 'client_id', 'bv_id', 'status', 'cache_hit', 'response_id', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
  - constraint: foreign key (response_id) references danmaku_responses(id) on delete set null
  - constraint: bv_id ~ '^BV[0-9A-Za-z]{10}$'
  - constraint: unique(client_id, bv_id, created_at::date)  -- soft dedupe per day
- `danmaku_responses.json` — Cached danmaku payloads for videos keyed by BV id, including parsed/normalized data and optional raw upstream format for debugging. (19 rows; fields: ['id', 'bv_id', 'status', 'danmaku_format', 'danmaku_items', 'raw_payload', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'purged']
  - constraint: unique(bv_id, fetched_at)
  - constraint: bv_id ~ '^BV[0-9A-Za-z]{10}$'

## Business rules enforced by the tools

- Every tool call must be attributable to exactly one api_clients row; unauthenticated requests are rejected.
- If api_clients.status != 'active' then all tools must reject the request.
- For search_user(keyword, page), the system must write a search_queries row with tool_name='search_user', search_type='user', and page set to the provided value (default 1).
- For general_search(keyword), the system must write a search_queries row with tool_name='general_search', search_type='general', and page=1.
- For get_precise_results(keyword, search_type), the system must write a search_queries row with tool_name='get_precise_results', search_type in {'user','video','live','article'} (default 'user'), and page=1.
- search_queries.upstream_cache_key must be deterministic for the tuple (tool_name, keyword, search_type, page); if a non-expired cached query exists, the server may set cache_hit=true and reuse its search_results instead of calling upstream.
- search_results rows must only be inserted/updated when the parent search_queries.status transitions to 'succeeded'.
- get_precise_results must return only search_results where exact_match=true and result_type equals the requested search_type; exact_match must be computed via a stable normalization rule (e.g., trim, case-fold, strip HTML tags) and stored.
- For get_video_danmaku(bv_id), the system must create a danmaku_requests row and either (a) set cache_hit=true and attach the latest non-expired danmaku_responses for that bv_id, or (b) fetch upstream and create a new danmaku_responses row then link danmaku_requests.response_id.
- danmaku_requests.status may only be set to 'succeeded' if response_id is non-null and references an existing danmaku_responses row.
- BV id inputs must match the pattern '^BV[0-9A-Za-z]{10}$'; otherwise requests fail validation before any upstream calls.
- Rate limiting must enforce api_clients.quota_per_minute and quota_per_day across all tools; requests beyond quota must be rejected and must not create search_queries/danmaku_requests rows (or must be recorded separately outside this schema).