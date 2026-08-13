# Brave-Gemini Research — local MCP environment

This backend supports a small research assistant that can run Brave web search, Brave local search, and Gemini-based research paper analysis. It stores authenticated clients (API keys), individual tool runs, the search results returned by Brave, and the documents/papers plus Gemini analyses produced from them, enabling auditing, rate limiting, and reproducibility.

Repository: https://github.com/falahgs/Brave-Gemini-Research-MCP-Server
Homepage: https://smithery.ai/server/@falahgs/brave-gemini-research-mcp-server

## Datastore

- `api_keys.json` — Client API keys used to authenticate calls to the MCP server and enforce per-key quotas/rate limits. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'requests_per_minute_limit', 'daily_request_limit', 'daily_usd_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit >= 1 and requests_per_minute_limit <= 6000
  - constraint: daily_request_limit >= 0
- `tool_runs.json` — Audit log and execution state for each tool invocation (brave_web_search, brave_local_search, gemini_research_paper_analysis). Stores inputs/outputs since tool schemas are empty but real calls still carry prompts/queries/content. (38 rows; fields: ['id', 'api_key_id', 'workspace_id', 'tool_name', 'status', 'request_payload', 'response_payload', 'error_code', 'error_message', 'upstream_provider', 'upstream_request_id', 'estimated_cost_usd', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: tool_name in ('brave_web_search','brave_local_search','gemini_research_paper_analysis')
  - constraint: estimated_cost_usd >= 0
  - constraint: completed_at is null when status in ('queued','running')
- `search_queries.json` — Normalized representation of a Brave search request derived from a tool_run (web or local). Used to support retries, caching, and per-query result grouping. (27 rows; fields: ['id', 'tool_run_id', 'query_text', 'search_type', 'location_hint', 'fallback_used', 'status', 'upstream_response_meta', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'fetched', 'error']
  - constraint: fk(tool_run_id) references tool_runs(id) on delete cascade
  - constraint: length(query_text) >= 1
  - constraint: search_type in ('web','local')
- `search_results.json` — Individual results returned by Brave for a given search query, including both web results and local business/place results. (35 rows; fields: ['id', 'search_query_id', 'rank', 'result_type', 'title', 'url', 'snippet', 'display_url', 'address', 'phone', 'opening_hours', 'rating', 'review_count', 'provider_payload', 'created_at', 'updated_at'])
  - constraint: fk(search_query_id) references search_queries(id) on delete cascade
  - constraint: unique(search_query_id, rank)
  - constraint: rank >= 1
  - constraint: rating is null or (rating >= 0 and rating <= 5)
- `paper_analyses.json` — Stores research paper documents (text/URL/metadata) and the Gemini-1.5-flash analysis outputs generated for them. (12 rows; fields: ['id', 'tool_run_id', 'source_type', 'source_url', 'title', 'authors', 'published_year', 'content_text', 'content_sha256', 'model', 'analysis_status', 'analysis_output', 'token_usage', 'created_at', 'updated_at'])
  - lifecycle `analysis_status`: ['pending', 'running', 'completed', 'failed']
  - constraint: fk(tool_run_id) references tool_runs(id) on delete cascade
  - constraint: model = 'gemini-1.5-flash'
  - constraint: published_year is null or (published_year >= 1800 and published_year <= 2100)
  - constraint: source_url is not null when source_type = 'url'

## Business rules enforced by the tools

- Every tool invocation creates exactly one tool_runs row with tool_name matching the called tool; status must start at 'queued' or 'running' and must follow the declared transitions.
- Requests authenticated with an api_key in status 'revoked' must be rejected and no tool_runs row may be created.
- For brave_web_search and brave_local_search, a tool_runs row that succeeds must have exactly one search_queries row linked by tool_run_id; failed/cancelled runs must not create search_results.
- For brave_local_search, if the system falls back to web search, search_queries.search_type must be 'local' and fallback_used must be true; resulting search_results may have result_type='web'.
- For each search_queries row, search_results.rank must be contiguous starting at 1 and unique per query (enforced by unique(search_query_id, rank)); rank must be >= 1.
- For gemini_research_paper_analysis, a succeeded tool_runs row must have exactly one paper_analyses row with analysis_status='completed' and non-null analysis_output.
- Daily and per-minute limits must be enforced per api_key_id: if the next request would exceed requests_per_minute_limit, daily_request_limit, or daily_usd_limit (based on accumulated tool_runs.estimated_cost_usd for the day), the request must fail with error_code='quota_exceeded' and tool_runs.status='failed'.
- All foreign keys must be valid at write time; deleting a tool_runs row must cascade-delete derived rows (search_queries, paper_analyses) and their children (search_results).
- PII/sensitive content must not be stored in error_message or response_payload; implementations must sanitize upstream errors before persisting.