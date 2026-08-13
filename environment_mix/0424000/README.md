# Tavily Web Search and Extraction Server — local MCP environment

This backend powers a web search, extraction, crawl, and site-mapping service similar to Tavily. It stores API clients, their requests (search/extract/crawl/map), and the resulting documents/URLs discovered, enforcing quotas, deduplication, and job lifecycles for long-running crawl/map operations.

Repository: https://github.com/Jeetanshu18/tavily-mcp
Homepage: https://smithery.ai/server/@Jeetanshu18/tavily-mcp

## Datastore

- `api_keys.json` — API credentials and quota configuration for clients calling tavily-search, tavily-extract, tavily-crawl, and tavily-map. (17 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'owner_type', 'owner_id', 'status', 'allowed_tools', 'rate_limit_rpm', 'monthly_request_quota', 'monthly_token_quota', 'usage_month', 'usage_requests', 'usage_tokens', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_rpm >= 1 and rate_limit_rpm <= 60000
  - constraint: monthly_request_quota >= 0
  - constraint: monthly_token_quota >= 0
- `requests.json` — Every invocation of tavily-search, tavily-extract, tavily-crawl, or tavily-map. Stores raw inputs/outputs for reproducibility, auditing, billing, and debugging; asynchronous tools progress via status. (19 rows; fields: ['id', 'api_key_id', 'tool', 'status', 'idempotency_key', 'input', 'normalized_target', 'response', 'error_code', 'error_message', 'http_status', 'tokens_used', 'result_count', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(api_key_id) references api_keys(id)
  - constraint: tokens_used >= 0
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: unique(api_key_id, tool, idempotency_key) where idempotency_key is not null
- `web_resources.json` — Canonical representation of URLs/pages discovered via search, extracted directly, crawled, or mapped. Supports deduplication across requests and stores lightweight metadata plus optional pointers to full content in object storage. (19 rows; fields: ['id', 'canonical_url', 'url_hash', 'host', 'title', 'description', 'content_text', 'content_html', 'content_storage_url', 'content_mime_type', 'http_status_last', 'fetched_at', 'first_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['discovered', 'fetched', 'fetch_failed', 'blocked']
  - constraint: unique(url_hash)
  - constraint: canonical_url != ''
  - constraint: http_status_last is null or (http_status_last >= 100 and http_status_last <= 599)
- `request_results.json` — Join table between requests and web_resources. Stores per-request ranking (search), extraction association, and crawl/map discovery context. (18 rows; fields: ['id', 'request_id', 'web_resource_id', 'result_type', 'rank', 'score', 'source_url_id', 'depth', 'anchor_text', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suppressed']
  - constraint: foreign key(request_id) references requests(id) on delete cascade
  - constraint: foreign key(web_resource_id) references web_resources(id)
  - constraint: foreign key(source_url_id) references web_resources(id)
  - constraint: rank is null or rank >= 1
- `crawl_jobs.json` — Structured crawl/map jobs for long-running traversal starting from a base URL. tavily-crawl and tavily-map both create jobs; job mode differentiates behavior (fetch+extract vs URL discovery only). (19 rows; fields: ['id', 'request_id', 'mode', 'status', 'base_web_resource_id', 'max_depth', 'max_pages', 'allowed_path_prefixes', 'blocked_path_prefixes', 'same_host_only', 'fetch_content', 'pages_discovered', 'pages_fetched', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(request_id) references requests(id) on delete cascade
  - constraint: foreign key(base_web_resource_id) references web_resources(id)
  - constraint: max_depth is null or (max_depth >= 0 and max_depth <= 50)
  - constraint: max_pages is null or (max_pages >= 1 and max_pages <= 100000)

## Business rules enforced by the tools

- All tool calls (tavily-search, tavily-extract, tavily-crawl, tavily-map) must create exactly one requests row and must increment api_keys.usage_requests by 1 on success or failure (excluding auth failures).
- If api_keys.status != 'active', the service must reject the call and must not create a requests row.
- If api_keys.allowed_tools is non-empty, the invoked requests.tool must be included; otherwise reject.
- Before executing a tool, enforce api_keys.rate_limit_rpm and monthly quotas; if exceeded, create a failed requests row with http_status=429 and do not perform external fetch/search.
- Idempotency: if (api_key_id, tool, idempotency_key) already exists, return the existing requests.response and do not create a new requests row.
- For tavily-search: persist each returned URL as a web_resources row (upsert by url_hash) and write request_results rows with result_type='search_hit' and increasing rank starting at 1.
- For tavily-extract: for each requested URL, upsert web_resources; after fetching, set web_resources.status to 'fetched' or 'fetch_failed' and create request_results with result_type='extracted'.
- For tavily-crawl and tavily-map: create a crawl_jobs row with mode matching the tool and a base_web_resource_id representing the base URL; job status must track requests.status (queued/running/succeeded/failed/cancelled).
- For crawl/map traversal, every discovered URL must be upserted into web_resources and linked via request_results with result_type 'crawled_page' or 'mapped_url', including depth and optional source_url_id for parent link.
- request_results.unique(request_id, web_resource_id, result_type) must be enforced to prevent duplicate outputs when the same URL is found multiple times; repeated discoveries should update metadata/depth to the shortest depth and keep the best (lowest) rank.
- web_resources.canonical_url must be normalized deterministically; url_hash must be computed from canonical_url and must be unique system-wide.
- requests.status transitions must follow the declared lifecycle; setting requests.status to succeeded/failed/cancelled must set finished_at.
- crawl_jobs.mode='map' must not store content_text/content_html unless an explicit server override is enabled; content should remain null and request_results should still be created.
- tokens_used must be recorded for every request and api_keys.usage_tokens must be incremented atomically with the request finalization to avoid double counting on retries.