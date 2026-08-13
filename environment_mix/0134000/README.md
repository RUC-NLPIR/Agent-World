# Reddit Trend Server — local MCP environment

Reddit Trend Server backs an API that fetches subreddit metadata, hot posts, trending-topic analysis, and search results, while also supporting cross-subreddit comparisons. The backend stores normalized subreddit and post snapshots plus derived analytics (trending topics, comparisons) and keeps an audit trail of API requests for rate limiting and debugging.

Repository: https://github.com/devfurkank/reddit-trend-mcp
Homepage: https://smithery.ai/server/@devfurkank/reddit-trend-mcp

## Datastore

- `api_requests.json` — Append-only log of tool invocations (inputs, timing, status, and optional cached result pointers). Supports operational observability, throttling, and reproducibility of analytics outputs. (19 rows; fields: ['id', 'tool_name', 'input', 'client_id', 'idempotency_key', 'status', 'http_status_code', 'error_message', 'duration_ms', 'cache_hit', 'result_ref', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: tool_name IN ('get_subreddit_hot_posts','get_subreddit_trending_topics','compare_subreddits','get_reddit_search','get_subreddit_info')
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: http_status_code IS NULL OR (http_status_code >= 100 AND http_status_code <= 599)
  - constraint: unique(client_id, idempotency_key) WHERE idempotency_key IS NOT NULL
- `subreddits.json` — Canonical subreddit entities and their periodically refreshed metadata snapshots used by get_subreddit_info and as a base for other tools. (18 rows; fields: ['id', 'name', 'display_name_prefixed', 'title', 'public_description', 'subscribers', 'active_user_count', 'nsfw', 'language', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'quarantined', 'banned', 'unknown']
  - constraint: unique(lower(name))
  - constraint: subscribers IS NULL OR subscribers >= 0
  - constraint: active_user_count IS NULL OR active_user_count >= 0
- `posts.json` — Stored Reddit post snapshots for hot lists and as the corpus for trending-topic and search responses. Rows represent latest-known state per Reddit thing id. (18 rows; fields: ['id', 'reddit_fullname', 'subreddit_id', 'title', 'selftext', 'url', 'author', 'score', 'upvote_ratio', 'num_comments', 'is_self', 'is_nsfw', 'created_utc', 'last_fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['visible', 'removed', 'deleted', 'unknown']
  - constraint: unique(reddit_fullname)
  - constraint: score IS NULL OR score >= 0
  - constraint: num_comments IS NULL OR num_comments >= 0
  - constraint: upvote_ratio IS NULL OR (upvote_ratio >= 0 AND upvote_ratio <= 1)
- `search_queries.json` — Persisted Reddit search requests and their result sets, enabling caching and returning consistent results for repeated queries. (19 rows; fields: ['id', 'api_request_id', 'query_text', 'subreddit_id', 'sort', 'time_filter', 'limit', 'status', 'executed_at', 'expires_at', 'result_post_ids', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: sort IN ('relevance','hot','top','new','comments')
  - constraint: time_filter IN ('all','year','month','week','day','hour')
  - constraint: limit >= 1 AND limit <= 100
  - constraint: result_post_ids IS NOT NULL
- `analytics_runs.json` — Derived analytics outputs: trending topic extraction for a subreddit and multi-subreddit comparisons. Used to cache expensive computations and provide consistent results. (20 rows; fields: ['id', 'api_request_id', 'analysis_type', 'primary_subreddit_id', 'subreddit_ids', 'time_filter', 'metric', 'source_post_ids', 'result', 'status', 'executed_at', 'expires_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: analysis_type IN ('subreddit_trending_topics','subreddit_compare')
  - constraint: CASE WHEN analysis_type='subreddit_trending_topics' THEN primary_subreddit_id IS NOT NULL AND time_filter IS NOT NULL AND metric IS NULL AND subreddit_ids IS NULL ELSE TRUE END
  - constraint: CASE WHEN analysis_type='subreddit_compare' THEN subreddit_ids IS NOT NULL AND metric IS NOT NULL AND primary_subreddit_id IS NULL AND time_filter IS NULL ELSE TRUE END
  - constraint: time_filter IS NULL OR time_filter IN ('hour','day','week','month','year','all')

## Business rules enforced by the tools

- For get_subreddit_info: if subreddits.lower(name) exists and last_fetched_at is recent (service TTL), return it; otherwise fetch from Reddit, upsert subreddits by unique(lower(name)), update last_fetched_at and status mapping (active/quarantined/banned/unknown), and log api_requests with result_ref pointing to subreddits.id.
- For get_subreddit_hot_posts: require a subreddit context resolved in input (default configured subreddit if client did not provide one); fetch hot listing, upsert posts by unique(reddit_fullname), enforce FK posts.subreddit_id exists, and return ordered posts for that subreddit. Update api_requests.result_ref to include subreddit_id and list of post ids.
- For get_reddit_search: create search_queries row with (query_text, subreddit_id nullable, sort, time_filter, limit). If an unexpired cached row exists per unique(subreddit_id, query_text, sort, time_filter), serve it and mark api_requests.cache_hit=true; otherwise execute search, upsert returned posts, store ordered posts.id into search_queries.result_post_ids, set status=succeeded, and set executed_at/expires_at.
- For get_subreddit_trending_topics: resolve subreddit_id, collect source posts within requested time_filter window (from posts.created_utc and/or fresh hot fetch), compute terms, store output in analytics_runs with analysis_type='subreddit_trending_topics'. If unexpired cached run exists for (primary_subreddit_id, time_filter), return it and set cache_hit=true.
- For compare_subreddits: resolve each subreddit_name to subreddits.id (creating placeholder rows with status='unknown' if necessary), compute requested metric over recent posts/subscriber snapshots, store in analytics_runs with analysis_type='subreddit_compare' and subreddit_ids ordered canonical. Enforce subreddit list length between 2 and 10 and metric in (activity, engagement, growth).
- All writes must maintain audit columns: created_at immutable after insert; updated_at changes on any update; last_fetched_at/executed_at set only when an external call/computation actually occurs.
- FK integrity: posts.subreddit_id must reference an existing subreddits row; search_queries.subreddit_id when non-null must reference subreddits.id; analytics_runs.primary_subreddit_id must reference subreddits.id when used; api_request_id references must point to existing api_requests rows.
- Lifecycle enforcement: api_requests.status and analytics/search status may only follow declared transitions; terminal states (succeeded/failed) are immutable.
- Range enforcement: upvote_ratio must be within [0,1]; counts (subscribers, active_user_count, score, num_comments, limit, duration_ms) must be non-negative; limit must be <= 100.
- Caching/TTL: expires_at must be set for search_queries and analytics_runs; expired rows may be reused only as historical records but must not be served as fresh cache hits.