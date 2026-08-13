# Tavily MCP Server — local MCP environment

This backend stores Tavily MCP requests for web search, extraction, crawling, and site mapping, along with their results, discovered URLs, and operational metadata. The main workflow is: a client issues a tool call, the system creates a job record, workers execute against external web resources, and results are stored as documents and URL graphs for later retrieval, auditing, and quota enforcement.

Repository: https://github.com/tavily-ai/tavily-mcp
Homepage: https://smithery.ai/server/@tavily-ai/tavily-mcp

## Datastore

- `workspaces.json` — Tenant container for API usage, quotas, and data isolation across tool calls (search/extract/crawl/map). (18 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_request_limit', 'monthly_token_limit', 'requests_used_month', 'tokens_used_month', 'usage_month', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_request_limit >= 0
  - constraint: monthly_token_limit >= 0
  - constraint: requests_used_month >= 0
- `api_keys.json` — API keys used to authenticate MCP tool calls; scoped to a workspace and used for usage attribution. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: key_prefix length between 4 and 16
- `tool_calls.json` — Canonical record of each MCP tool invocation (tavily-search, tavily-extract, tavily-crawl, tavily-map) including normalized inputs, execution status, and usage attribution. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'requested_at', 'started_at', 'finished_at', 'expires_at', 'input', 'normalized_input', 'error_code', 'error_message', 'http_user_agent', 'source_ip', 'estimated_tokens', 'billed_tokens', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: requested_at <= created_at + interval '5 minutes'
  - constraint: started_at is null or started_at >= requested_at
- `web_resources.json` — Deduplicated URLs and fetched content metadata used by extract/crawl/map and to enrich search results. (18 rows; fields: ['id', 'canonical_url', 'url_hash', 'domain', 'last_fetch_status', 'last_fetched_at', 'content_type', 'content_language', 'content_sha256', 'raw_content', 'clean_content', 'title', 'robots_allowed', 'created_at', 'updated_at'])
  - lifecycle `robots_allowed`: [True, False]
  - constraint: unique(url_hash)
  - constraint: canonical_url matches ^https?://
  - constraint: last_fetch_status is null or (last_fetch_status >= 100 and last_fetch_status <= 599)
  - constraint: content_sha256 is null or length(content_sha256) = 64
- `tool_call_results.json` — Result items produced by a tool call: search hits, extracted documents, crawl-discovered pages, and site map nodes/edges. Designed to support multi-item outputs and URL graph storage. (19 rows; fields: ['id', 'tool_call_id', 'workspace_id', 'kind', 'rank', 'web_resource_id', 'from_web_resource_id', 'to_web_resource_id', 'payload', 'created_at', 'updated_at'])
  - lifecycle `kind`: ['search_hit', 'extracted_document', 'crawl_page', 'map_node', 'map_edge']
  - constraint: foreign key(tool_call_id) references tool_calls(id) on delete cascade
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key(web_resource_id) references web_resources(id) on delete set null
  - constraint: foreign key(from_web_resource_id) references web_resources(id) on delete set null

## Business rules enforced by the tools

- Each MCP invocation of tavily-search, tavily-extract, tavily-crawl, or tavily-map must create exactly one tool_calls row with tool_name set accordingly, and input persisted verbatim.
- A tool call may only move between statuses following the declared lifecycle transitions; any attempt to skip directly from queued to succeeded must be rejected.
- When tool_calls.status becomes running, started_at must be set; when status becomes succeeded/failed/cancelled/expired, finished_at must be set and must be >= started_at.
- For any authenticated request, api_key_id must belong to the same workspace_id; otherwise the request must be rejected.
- Before accepting a new tool call, the system must verify workspaces.status = 'active' and that requests_used_month + 1 <= monthly_request_limit; otherwise fail with error_code = 'quota_exceeded'.
- For extract/crawl/map workloads, the system must estimate tokens (estimated_tokens) before execution and ensure tokens_used_month + estimated_tokens <= monthly_token_limit; otherwise fail with error_code = 'quota_exceeded'.
- On successful completion, billed_tokens must be computed and applied atomically: increment workspaces.requests_used_month by 1 and tokens_used_month by billed_tokens, and set tool_calls.billed_tokens = billed_tokens.
- web_resources must be deduplicated by canonical_url via url_hash; inserting a URL that already exists must upsert metadata (last_fetched_at, status, hashes) without creating duplicates.
- If robots_allowed is false for a web_resource at time of fetch, the system must not store raw_content/clean_content and any tool call relying on it must record failure or partial output per policy with error_code = 'robots_disallowed' for affected URLs.
- tool_call_results.workspace_id must always equal tool_calls.workspace_id for the referenced tool_call_id; writes violating this must be rejected.
- tavily-search must emit tool_call_results rows with kind='search_hit' and ranked ordering (rank) when applicable; associated URLs must map to web_resources rows.
- tavily-extract must emit tool_call_results rows with kind='extracted_document' for each requested URL; payload must include extraction metadata and web_resource content hashes must be updated.
- tavily-crawl must emit tool_call_results rows with kind='crawl_page' for each visited page and may also emit map_edge/map_node rows if link structure is captured; all discovered URLs must be canonicalized and stored in web_resources.
- tavily-map must emit tool_call_results rows with kind='map_node' for each discovered URL and kind='map_edge' for each discovered internal link; map_edge must always reference existing map_node URLs within the same tool_call_id.
- Expired tool calls (status='expired') must not accept new tool_call_results writes and may have their associated web_resources content fields truncated or removed by retention jobs without breaking referential integrity.