# Brave Search — local MCP environment

This backend stores Brave Search requests made through an MCP server, the normalized results returned by Brave (web/news/image/video/local), and the API credentials and usage accounting needed to enforce rate limits and audit activity. Main workflows: authenticate a caller via an API key, record a search request, call Brave upstream, persist results, and increment per-key usage counters with quota enforcement.

Repository: https://github.com/JonyanDunh/brave-search-mcp
Homepage: https://smithery.ai/server/@JonyanDunh/brave-search-mcp

## Datastore

- `api_keys.json` — API keys that authorize callers of this MCP service and tie requests to quotas, logging, and revocation lifecycle. (13 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'daily_request_limit', 'burst_rps_limit', 'allowed_tools', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: daily_request_limit >= 0
  - constraint: burst_rps_limit >= 0
- `search_requests.json` — One record per tool invocation (web/news/image/video/local). Stores the request metadata, lifecycle, and links to persisted results. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'query_text', 'requested_limit', 'effective_limit', 'client_metadata', 'upstream_provider', 'upstream_request_id', 'fallback_used', 'status', 'error_code', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: requested_limit between 1 and 20
  - constraint: effective_limit between 1 and 20
  - constraint: effective_limit <= requested_limit or effective_limit == 20 when requested_limit > 20
- `search_results.json` — Normalized result items returned by Brave for a given search request (up to 20). Stores common fields across web/news/image/video/local and type-specific payload in a JSON object. (18 rows; fields: ['id', 'search_request_id', 'rank', 'result_type', 'title', 'url', 'description', 'source', 'published_at', 'thumbnail_url', 'payload', 'created_at', 'updated_at'])
  - lifecycle `result_type`: ['web', 'news', 'image', 'video', 'local']
  - constraint: fk(search_request_id) references search_requests(id) on delete cascade
  - constraint: unique(search_request_id, rank)
  - constraint: rank between 1 and 20
  - constraint: result_type in ('web','news','image','video','local')
- `usage_counters.json` — Aggregated per-API-key usage for quota enforcement and reporting, tracked per UTC day and per tool. (18 rows; fields: ['id', 'api_key_id', 'usage_date', 'tool_name', 'request_count', 'success_count', 'error_count', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['brave_web_search', 'brave_news_search', 'brave_image_search', 'brave_video_search', 'brave_local_search']
  - constraint: fk(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, usage_date, tool_name)
  - constraint: request_count >= 0
  - constraint: success_count >= 0

## Business rules enforced by the tools

- Each invocation of brave_web_search, brave_news_search, brave_image_search, brave_video_search, or brave_local_search MUST create exactly one search_requests row tied to the authenticating api_keys row.
- For any request, effective_limit MUST be clamped to [1,20]; if the caller asks for more than 20, the service MUST set effective_limit to 20 and record the original requested_limit.
- A search_request MUST NOT transition out of 'succeeded', 'failed', or 'cancelled'.
- For every succeeded request, the service MUST persist between 0 and effective_limit rows in search_results, with unique ranks starting at 1; ranks MUST NOT exceed 20.
- The brave_local_search tool MUST set fallback_used=true if it returns results sourced from web search; in that case the stored tool_name remains 'brave_local_search' and result_type MUST be 'web' or 'local' consistent with returned items.
- Requests MUST be rejected when api_keys.status is not 'active'.
- Requests MUST be rejected when api_keys.allowed_tools is non-empty and does not include the invoked tool_name.
- Before executing upstream, the service MUST enforce daily quota: sum(usage_counters.request_count) for the api_key_id and usage_date across all tools MUST be <= api_keys.daily_request_limit; otherwise the request MUST be recorded as failed with error_code='quota_exceeded' and no upstream call attempted.
- On completion of each request, the service MUST increment usage_counters for the corresponding api_key_id, usage_date, and tool_name: request_count += 1 and success_count or error_count += 1 based on final status.
- Foreign keys MUST be enforced: deleting a search_request MUST cascade delete its search_results; deleting an api_key MUST cascade delete its usage_counters but MUST be restricted if historical search_requests retention policy requires preservation (implement as soft-delete via status='revoked' in production).