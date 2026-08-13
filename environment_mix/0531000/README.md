# Exa Search — local MCP environment

This backend stores Exa-style search and extraction activity: user-issued searches across multiple verticals (web, papers, company, competitors, LinkedIn, Wikipedia, GitHub) and URL crawling/extraction jobs. Core workflows are: create a query or crawl request, execute it against Exa, persist the normalized results/content, and track status, latency, and usage costs/limits for operational control.

Repository: https://github.com/exa-labs/exa-mcp-server
Homepage: https://smithery.ai/server/exa

## Datastore

- `api_keys.json` — API keys used to authenticate/attribute requests to a caller and enforce basic quotas/rate limits. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'quota_requests_per_day', 'quota_chars_extracted_per_day', 'rate_limit_rps', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: quota_requests_per_day >= 0
  - constraint: quota_chars_extracted_per_day >= 0
- `search_requests.json` — A single logical search call (web/papers/company/competitors/linkedin/wikipedia/github). Stores parameters, execution status, and summary metrics. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'vertical', 'query', 'company_name', 'industry', 'search_type', 'num_results_requested', 'status', 'error_code', 'error_message', 'upstream_request_id', 'started_at', 'finished_at', 'latency_ms', 'results_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: num_results_requested between 1 and 50
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: results_count is null or results_count >= 0
  - constraint: tool_name in (web_search_exa, research_paper_search_exa, company_research_exa, competitor_finder_exa, linkedin_search_exa, wikipedia_search_exa, github_search_exa)
- `search_results.json` — Normalized result rows for a search request (URLs, titles, snippets, and optional entity-specific metadata). (18 rows; fields: ['id', 'search_request_id', 'rank', 'url', 'domain', 'title', 'snippet', 'published_at', 'author', 'source_type', 'entity_metadata', 'relevance_score', 'created_at', 'updated_at'])
  - constraint: unique(search_request_id, rank)
  - constraint: rank >= 1
  - constraint: url <> ''
  - constraint: relevance_score is null or relevance_score >= 0
- `crawl_jobs.json` — URL extraction/crawling jobs (crawling_exa tool). Stores requested limits, execution status, and response metadata. (18 rows; fields: ['id', 'api_key_id', 'url', 'max_characters', 'status', 'http_status', 'content_type', 'charset', 'error_code', 'error_message', 'started_at', 'finished_at', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(api_key_id, url, max_characters, created_at) (soft-dedupe window enforced by application)
  - constraint: max_characters between 256 and 100000
  - constraint: http_status is null or http_status between 100 and 599
  - constraint: latency_ms is null or latency_ms >= 0
- `crawl_documents.json` — Extracted content and metadata for completed crawl jobs. Separated from crawl_jobs to keep large text payloads isolated and optionally stored/compressed. (18 rows; fields: ['id', 'crawl_job_id', 'final_url', 'title', 'meta_description', 'text_content', 'excerpt', 'language', 'outbound_links', 'structured_data', 'characters_extracted', 'created_at', 'updated_at'])
  - constraint: unique(crawl_job_id)
  - constraint: characters_extracted >= 0
  - constraint: characters_extracted <= 100000
  - constraint: text_content is null or length(text_content) = characters_extracted (enforced by application)

## Business rules enforced by the tools

- Every tool invocation must be attributed to exactly one api_keys.id; requests with api_keys.status != 'active' are rejected and not persisted beyond a minimal audit log (if any).
- web_search_exa, research_paper_search_exa, linkedin_search_exa, wikipedia_search_exa, github_search_exa must persist search_requests.query (non-empty) and must not set company_name.
- company_research_exa and competitor_finder_exa must persist search_requests.company_name (non-empty) and must not set query.
- competitor_finder_exa may set industry; other tools must leave industry null.
- linkedin_search_exa searchType maps to search_requests.search_type in {'profiles','companies','all'}; github_search_exa searchType maps to {'repositories','code','users','all'}; other tools must leave search_type null.
- numResults defaults to 5 when omitted; it is clamped/validated to [1,50] before execution and stored in search_requests.num_results_requested.
- For each search_request that succeeds, exactly results_count rows exist in search_results with ranks 1..results_count and unique(search_request_id, rank).
- crawling_exa must create a crawl_jobs row with maxCharacters defaulting to 3000 when omitted and validated to [256,100000].
- For each crawl_job that succeeds, exactly one crawl_documents row exists; for failed/cancelled jobs, none exists.
- Daily quotas: for each api_key, the number of created search_requests + crawl_jobs per UTC day must be <= quota_requests_per_day; additionally sum(crawl_documents.characters_extracted) per UTC day must be <= quota_chars_extracted_per_day (enforced transactionally at write time).
- Status transitions must follow the declared lifecycle graphs; updates attempting invalid transitions are rejected.
- FK integrity: deleting an api_key is forbidden if referenced by any search_requests or crawl_jobs; deleting search_requests/crawl_jobs is either forbidden or requires cascading delete of dependent search_results/crawl_documents (operator-controlled).