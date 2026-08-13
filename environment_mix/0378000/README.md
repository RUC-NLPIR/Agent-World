# Exa Server — local MCP environment

This backend stores Exa-powered search and crawl requests, the resulting documents/snippets returned to callers, and the per-tenant API access controls needed to enforce quotas. Core workflows: authenticate an API key, create a search or crawl request with tool-specific parameters, execute against Exa, store results and extracted content, and meter usage for billing/limits.

Repository: https://github.com/arjunkmrm/exa-mcp-server
Homepage: https://smithery.ai/server/@arjunkmrm/exa-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace container for API keys, quotas, and all search/crawl activity. (12 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_request_limit', 'monthly_char_extract_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_request_limit >= 0
  - constraint: monthly_char_extract_limit >= 0
- `api_keys.json` — API keys used to authenticate requests and associate them to a workspace; includes state and rotation metadata. (17 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
- `search_requests.json` — A single user-initiated search operation across supported tools (web, research papers, company research, competitor finder, LinkedIn, Wikipedia, GitHub). Stores tool parameters and execution metadata. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool', 'query', 'company_name', 'industry', 'search_type', 'num_results', 'status', 'error_code', 'error_message', 'exa_request_id', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: num_results between 1 and 20
  - constraint: tool in (web_search_exa,research_paper_search_exa,company_research_exa,competitor_finder_exa,linkedin_search_exa,wikipedia_search_exa,github_search_exa)
- `search_results.json` — Ranked result items returned for a search request (URLs and metadata/snippets). (18 rows; fields: ['id', 'search_request_id', 'rank', 'url', 'title', 'snippet', 'source', 'score', 'published_at', 'raw_metadata', 'created_at', 'updated_at'])
  - constraint: fk(search_request_id) references search_requests(id) on delete cascade
  - constraint: unique(search_request_id, rank)
  - constraint: rank >= 1
  - constraint: unique(search_request_id, url)
- `crawl_requests.json` — A single URL extraction/crawl job (maps to crawling_exa). Stores requested maxCharacters and the extracted content/metadata. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'url', 'max_characters', 'status', 'http_status', 'content_type', 'title', 'extracted_text', 'extracted_characters', 'raw_metadata', 'error_code', 'error_message', 'exa_request_id', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: max_characters between 100 and 100000
  - constraint: check(status != succeeded or extracted_text is not null)
- `usage_ledger.json` — Append-only metering ledger to enforce monthly quotas and support billing/analytics; each entry ties to a search or crawl request. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'event_type', 'search_request_id', 'crawl_request_id', 'requests', 'extracted_characters', 'billed_at', 'created_at', 'updated_at'])
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: requests >= 0
  - constraint: extracted_characters >= 0

## Business rules enforced by the tools

- All tool calls must authenticate with an api_keys row where status='active' and the owning workspaces.status='active'.
- web_search_exa, research_paper_search_exa, linkedin_search_exa, wikipedia_search_exa, github_search_exa must create a search_requests row with query set, company_name null, num_results defaulting to 5 when omitted.
- company_research_exa and competitor_finder_exa must create a search_requests row with company_name set, query null, num_results defaulting to 5 when omitted; competitor_finder_exa may also set industry.
- linkedin_search_exa.searchType must be one of profiles|companies|all; github_search_exa.searchType must be one of repositories|code|users|all; if omitted, search_type is stored as 'all' at execution time.
- numResults must be clamped/rejected to an integer in [1,20] before persistence and execution.
- crawling_exa must create a crawl_requests row with url set and max_characters defaulting to 3000 when omitted; max_characters must be an integer within [100,100000].
- For each succeeded search_requests, exactly N search_results rows must be persisted where N equals min(num_results, results_returned_by_upstream), with unique(rank) and unique(url) per request.
- For each succeeded crawl_requests, extracted_text must be non-null and extracted_characters must equal length(extracted_text) and be <= max_characters.
- Status transitions must follow the declared lifecycle graphs; attempts to move from terminal states (succeeded/failed/cancelled) must be rejected.
- A usage_ledger event must be written exactly once per finished request (search or crawl) with requests=1 and extracted_characters equal to crawl_requests.extracted_characters for crawl events (0 for search events unless the implementation performs content extraction for results).
- Before executing a request, the system must enforce workspace monthly quotas: sum(usage_ledger.requests) for the workspace in the billed_at month + 1 must be <= workspaces.monthly_request_limit, and sum(usage_ledger.extracted_characters) + planned_extract_chars must be <= workspaces.monthly_char_extract_limit; otherwise the request must fail with a quota error and be recorded as failed without writing a usage_ledger charge.