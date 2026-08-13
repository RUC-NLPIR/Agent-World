# Google Search — local MCP environment

This backend stores authenticated client access to a Google-search proxy API, including API keys, per-request search queries, and the returned result items for audit, caching, and analytics. The main workflow is: a client issues a search request (query + options), the system executes it (or serves from cache), stores the query record and the normalized results, and enforces quotas/timeouts per API key/workspace.

Repository: https://github.com/modelcontextprotocol-servers/google-search-mcp
Homepage: https://smithery.ai/server/@modelcontextprotocol-servers/google-search-mcp

## Datastore

- `workspaces.json` — Tenant/workspace container for API usage, quotas, and ownership. API keys belong to a workspace; queries are executed within a workspace context. (12 rows; fields: ['id', 'name', 'status', 'default_language', 'default_region', 'monthly_request_quota', 'monthly_result_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_request_quota >= 0
  - constraint: monthly_result_quota >= 0
  - constraint: default_language <> ''
- `api_keys.json` — API keys used by clients to call the service. Stores hashed secret material, status, and per-key throttles; all calls (including search) are attributed to an api_key and workspace. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'rate_limit_rpm', 'max_timeout_ms', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: rate_limit_rpm between 1 and 6000
- `search_queries.json` — A single search request issued by a client. Captures the tool parameters (query, limit, timeout, language, region), execution status, latency, error information, and whether it was served from cache. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'query', 'limit', 'timeout_ms', 'language', 'region', 'request_fingerprint', 'status', 'served_from_cache', 'cache_expires_at', 'http_status_code', 'error_code', 'error_message', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: limit between 1 and 100
  - constraint: timeout_ms between 1000 and 120000
- `search_results.json` — Individual result items returned for a search query. Stores rank/order and basic metadata used by clients (title, url, snippet). (18 rows; fields: ['id', 'search_query_id', 'rank', 'title', 'url', 'display_url', 'snippet', 'source', 'raw', 'created_at', 'updated_at'])
  - lifecycle `source`: ['google']
  - constraint: foreign key(search_query_id) references search_queries(id) on delete cascade
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, url)
  - constraint: rank >= 1
- `usage_buckets.json` — Pre-aggregated usage counters used to enforce workspace quotas and support reporting. Updated transactionally when a search query completes successfully (or partially, depending on policy). (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'period', 'period_start', 'requests_count', 'results_count', 'timeouts_count', 'failures_count', 'created_at', 'updated_at'])
  - lifecycle `period`: ['month']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: unique(workspace_id, api_key_id, period, period_start)
  - constraint: requests_count >= 0

## Business rules enforced by the tools

- Every search tool call must authenticate to exactly one api_keys row with status='active' and inherit its workspace_id.
- The search tool parameter `query` maps to search_queries.query and must be non-empty after trimming; otherwise the request is rejected.
- `limit` defaults to 10 when omitted; persisted as search_queries.limit; enforce 1 <= limit <= 100.
- `timeout` defaults to 60000 when omitted; persisted as search_queries.timeout_ms; enforce 1000 <= timeout_ms <= min(120000, api_keys.max_timeout_ms).
- `language` defaults to workspaces.default_language (or zh-CN if not set) and is persisted as search_queries.language.
- `region` defaults to workspaces.default_region (or cn if not set) and is persisted as search_queries.region.
- A search query row must be created with status='queued' then transition through the declared lifecycle; status must never move backward or change after terminal states (succeeded/failed/timed_out/cancelled).
- If a cached response is returned (served_from_cache=true), the system must still store a search_queries row and associated search_results rows linked by search_query_id, and must set cache_expires_at to a non-null value in the future at time of serving.
- On succeeded queries, exactly N search_results rows must be created where N == search_queries.limit (unless upstream returns fewer; then N <= limit) and ranks must be consecutive starting at 1.
- Quota enforcement: before execution begins, ensure workspace monthly_request_quota is not exceeded for the current month; after completion, increment usage_buckets.requests_count for that month and increment results_count by number of stored search_results rows for that query.
- If workspace monthly_result_quota would be exceeded by returning results, the request must be rejected or truncated so that results_count never exceeds the quota (policy-dependent but must be consistent).
- search_queries.duration_ms must equal finished_at - started_at (in ms) when both timestamps are present.
- Foreign key integrity must hold: search_results.search_query_id must reference an existing search_queries.id; api_keys.workspace_id must reference workspaces.id; search_queries.api_key_id must reference api_keys.id and search_queries.workspace_id must match api_keys.workspace_id.