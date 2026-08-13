# TMDB Server — local MCP environment

This backend powers a TMDB proxy/search service that records inbound tool calls (search, trending, recommendations), caches TMDB movie metadata and response payloads for performance, and enforces API key usage limits. Main workflows are: client calls a tool -> request is logged -> cache is consulted/filled -> response is returned and usage counters updated.

Repository: https://github.com/Laksh-star/mcp-server-tmdb
Homepage: https://smithery.ai/server/@Laksh-star/mcp-server-tmdb

## Datastore

- `api_keys.json` — Issued API keys for clients of this TMDB Server, including status and quota controls. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'plan', 'quota_requests_per_day', 'quota_requests_per_minute', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: quota_requests_per_day >= 0
  - constraint: quota_requests_per_minute >= 0
  - constraint: plan in ('free','pro','internal')
- `movies.json` — Locally cached movie metadata sourced from TMDB, keyed by TMDB movie id. (18 rows; fields: ['id', 'tmdb_movie_id', 'title', 'original_title', 'overview', 'release_date', 'language', 'popularity', 'vote_average', 'vote_count', 'poster_path', 'backdrop_path', 'adult', 'status', 'tmdb_last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: unique(tmdb_movie_id)
  - constraint: tmdb_movie_id > 0
  - constraint: vote_count is null or vote_count >= 0
  - constraint: vote_average is null or (vote_average >= 0 and vote_average <= 10)
- `tool_requests.json` — Audit log of all tool invocations (search_movies, get_recommendations, get_trending), including parameters (empty for this tool surface), cache behavior, and response linkage. (17 rows; fields: ['id', 'api_key_id', 'tool_name', 'parameters', 'status', 'http_status', 'error_code', 'error_message', 'cache_mode', 'response_id', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'processing', 'succeeded', 'failed']
  - constraint: parameters is a JSON object
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: tool_name in ('search_movies','get_recommendations','get_trending')
  - constraint: cache_mode in ('miss','hit','bypass')
- `tmdb_responses.json` — Cache of TMDB API responses for the supported tools, keyed by a deterministic cache key derived from tool and parameters (empty parameters still produce stable keys). Also stores extracted movie ids for analytics and joins. (18 rows; fields: ['id', 'tool_name', 'cache_key', 'source_url', 'response_json', 'movie_tmdb_ids', 'status', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'purged']
  - constraint: unique(tool_name, cache_key)
  - constraint: tool_name in ('search_movies','get_recommendations','get_trending')
  - constraint: expires_at is null or expires_at >= fetched_at
  - constraint: response_json is a JSON object
- `api_key_usage_buckets.json` — Aggregated usage counters per API key and time bucket to enforce per-minute and per-day request quotas. (17 rows; fields: ['id', 'api_key_id', 'bucket_type', 'bucket_start', 'request_count', 'last_request_at', 'created_at', 'updated_at'])
  - lifecycle `bucket_type`: ['minute', 'day']
  - constraint: unique(api_key_id, bucket_type, bucket_start)
  - constraint: request_count >= 0
  - constraint: bucket_type in ('minute','day')

## Business rules enforced by the tools

- Every tool invocation (search_movies, get_recommendations, get_trending) MUST insert a tool_requests row with tool_name and parameters={}, transitioning status from received -> processing -> (succeeded|failed).
- If a request provides an API key, api_keys.status MUST be 'active' or the request is rejected and tool_requests.status='failed' with http_status=401/403.
- For keyed requests, the service MUST upsert api_key_usage_buckets for bucket_type='minute' and bucket_type='day' (bucket_start truncated to minute/day UTC) and MUST reject requests that would make request_count exceed api_keys.quota_requests_per_minute or api_keys.quota_requests_per_day.
- Caching: the service MUST compute tmdb_responses.cache_key deterministically from tool_name and normalized parameters (empty object still produces a stable key). If a non-expired tmdb_responses row exists with status='fresh', tool_requests.cache_mode='hit' and response_id references it; otherwise cache_mode='miss' and a new/updated tmdb_responses row is written.
- When writing tmdb_responses, response_json MUST be stored, fetched_at MUST be set, and expires_at SHOULD be set according to server TTL policy; when now >= expires_at, the entry SHOULD transition to status='stale'.
- For responses that contain movie results, the implementation SHOULD extract TMDB movie IDs into tmdb_responses.movie_tmdb_ids and upsert corresponding movies rows (unique by tmdb_movie_id) with tmdb_last_fetched_at set.
- movies rows MUST maintain vote_average within [0,10] when present and vote_count >= 0 when present; tmdb_movie_id MUST be > 0.
- A tool_requests row with status='succeeded' MUST have http_status in [200,299] and response_id non-null; a tool_requests row with status='failed' MUST have http_status in [400,599] and error_message non-null.
- Deleting/purging cached payloads MUST transition tmdb_responses.status to 'purged' (no transitions out of purged) and MUST NOT break FK integrity for historical tool_requests; instead tool_requests.response_id may be set to NULL if purge requires.