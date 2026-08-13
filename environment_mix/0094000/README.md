# Search1API MCP Server — local MCP environment

This backend powers a multi-tool web intelligence API: general search, news search, trending topics, sitemap discovery, URL crawling/content extraction, and a reasoning endpoint that synthesizes answers from retrieved/crawled content. It stores API clients/keys, request logs, extracted documents, discovered links, and usage/quota enforcement needed to operate these tools at production scale.

Repository: https://github.com/fatwang2/search1api-mcp
Homepage: https://smithery.ai/server/search1api-mcp

## Datastore

- `api_clients.json` — Represents a tenant/workspace consuming the Search1API MCP Server. Owns API keys, quotas, and all generated artifacts (requests, crawls, sitemaps). (18 rows; fields: ['id', 'display_name', 'status', 'plan', 'monthly_request_limit', 'monthly_token_limit', 'monthly_crawl_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(display_name)
  - constraint: monthly_request_limit >= 0
  - constraint: monthly_token_limit >= 0
  - constraint: monthly_crawl_limit >= 0
- `api_keys.json` — API keys used to authenticate tool calls. Tracks status, rotation, and last usage for abuse control. (18 rows; fields: ['id', 'client_id', 'key_hash', 'key_prefix', 'status', 'name', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: unique(key_hash)
  - constraint: unique(client_id, name) where name is not null
  - constraint: key_prefix length between 4 and 16
- `tool_requests.json` — Immutable request/response ledger for every tool call (search/news/crawl/sitemap/reasoning/trending). Supports rate limiting, debugging, and analytics. (20 rows; fields: ['id', 'client_id', 'api_key_id', 'tool_name', 'status', 'request_payload', 'response_payload', 'http_status', 'error_code', 'error_message', 'ip_address', 'user_agent', 'latency_ms', 'compute_units', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'throttled']
  - constraint: compute_units >= 0
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: http_status is null or (http_status between 100 and 599)
- `web_documents.json` — Canonical representation of a fetched URL and its extracted content/metadata. Used by crawl, can be referenced by search/news results, and can be fed into reasoning. (19 rows; fields: ['id', 'client_id', 'source_request_id', 'url', 'url_hash', 'status', 'http_status', 'content_type', 'title', 'language', 'published_at', 'raw_text', 'html', 'outgoing_links', 'content_sha256', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'extracted', 'blocked', 'error', 'deleted']
  - constraint: unique(client_id, url_hash)
  - constraint: http_status is null or (http_status between 100 and 599)
  - constraint: array_length(outgoing_links) >= 0
- `sitemaps.json` — Stores sitemap discovery runs and the set of related links found for a seed URL/domain. Serves the sitemap tool and can feed crawl and reasoning workflows. (20 rows; fields: ['id', 'client_id', 'source_request_id', 'seed_url', 'seed_url_hash', 'status', 'discovered_links', 'discovered_count', 'failure_reason', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'cancelled']
  - constraint: unique(client_id, seed_url_hash, source_request_id)
  - constraint: discovered_count >= 0
  - constraint: discovered_count = array_length(discovered_links)

## Business rules enforced by the tools

- Every tool invocation (search, news, crawl, sitemap, reasoning, trending) must create exactly one tool_requests row with tool_name set accordingly and status transitioning received -> running -> (succeeded|failed) or received -> throttled.
- Requests must be rejected/throttled (tool_requests.status='throttled') when the client or api_key is not active, or when the client exceeds monthly_request_limit.
- Reasoning calls must increment compute_units according to tokens/compute consumed and must be rejected/throttled when the client exceeds monthly_token_limit for the current calendar month (sum(tool_requests.compute_units) where tool_name='reasoning').
- Crawl and sitemap calls must be rejected/throttled when the client exceeds monthly_crawl_limit for the current calendar month (count(tool_requests) where tool_name in ('crawl','sitemap') and status in ('succeeded','failed')).
- A web_documents row must be upserted by (client_id, url_hash) on crawl; url_hash must be computed from a normalized URL (scheme/host lowercased, default ports removed, fragments removed).
- web_documents.status may only transition per the declared lifecycle; extracted documents may be re-queued for refresh but deleted is terminal.
- A sitemaps row must be created for each sitemap tool request; discovered_links must be normalized URLs and discovered_count must equal the number of links stored.
- api_keys.key_hash must be globally unique; raw API key material must never be stored in any collection.
- Deleting a client (api_clients.status='deleted') must prevent new tool_requests and should cascade soft-delete (status='deleted') for associated web_documents and mark future sitemap/crawl operations as throttled or failed with an appropriate error_code.
- tool_requests.response_payload must be null while status is received/running and must be non-null for succeeded/failed/throttled except for internal logging suppression cases.