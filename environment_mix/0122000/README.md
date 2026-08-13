# Firecrawl Web Scraping Server — local MCP environment

This backend stores web acquisition jobs (single-page scrapes, batch scrapes, crawls, and URL maps), along with the resulting pages/content and higher-level AI workflows (search, extraction, deep research, llms.txt generation). The main workflow is: a client submits a job (or query) -> the system schedules fetch/scrape -> stores pages and derived artifacts -> exposes status/result retrieval for async jobs.

Repository: https://github.com/Krieg2065/firecrawl-mcp-server
Homepage: https://smithery.ai/server/@Krieg2065/firecrawl-mcp-server

## Datastore

- `workspaces.json` — Tenant boundary for API usage. Jobs, pages, and research runs belong to a workspace and are accessed via API keys. (12 rows; fields: ['id', 'name', 'plan', 'status', 'monthly_page_limit', 'monthly_llm_token_limit', 'usage_month', 'pages_used', 'llm_tokens_used', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: monthly_page_limit >= 0
  - constraint: monthly_llm_token_limit >= 0
  - constraint: pages_used >= 0
- `api_keys.json` — API credentials that authenticate calls to all tools; used for workspace scoping, quotas, and audit. (27 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_prefix)
  - constraint: key_prefix length between 6 and 16
  - constraint: key_hash length >= 32
- `jobs.json` — Unified job table for all tool invocations that produce async or sync results: scrape, map, crawl, batch scrape, search, extract, deep research, and llms.txt generation. (38 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool', 'status', 'priority', 'input', 'webhook_url', 'webhook_secret', 'started_at', 'finished_at', 'error_code', 'error_message', 'result_summary', 'pages_fetched', 'llm_tokens_used', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: priority between -10 and 10
  - constraint: pages_fetched >= 0
- `job_items.json` — Per-URL work items and outputs for multi-target jobs (batch scrape, crawl, map expansions, search results, deep research sources). Also used for single scrape/search/extract to store the canonical set of URLs produced by a job. (30 rows; fields: ['id', 'job_id', 'sequence', 'url', 'parent_url', 'depth', 'kind', 'status', 'http_status', 'title', 'description', 'page_id', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'scraping', 'succeeded', 'failed', 'skipped']
  - constraint: fk(job_id) references jobs(id) on delete cascade
  - constraint: fk(page_id) references pages(id) on delete set null
  - constraint: unique(job_id, sequence)
  - constraint: unique(job_id, url) where kind in ('batch_target','crawl_page','discovered','seed')
- `pages.json` — Canonical store of fetched/scraped page artifacts used across scrape, batch, crawl, search-with-scrape, extract, deep research, and llms.txt generation. (42 rows; fields: ['id', 'workspace_id', 'source_job_id', 'url', 'fetched_url', 'status', 'content_type', 'language', 'title', 'html', 'text', 'markdown', 'metadata', 'extracted_data', 'llms_txt', 'content_sha256', 'created_at', 'updated_at'])
  - lifecycle `status`: ['stored', 'redacted', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(source_job_id) references jobs(id) on delete set null
  - constraint: url matches ^https?://
  - constraint: content_sha256 is null or matches ^[a-f0-9]{64}$

## Business rules enforced by the tools

- All tool invocations must authenticate via an active api_keys record whose workspace is in status=active.
- firecrawl_scrape creates a jobs row with tool=firecrawl_scrape; if synchronous execution is configured, the job may transition queued->running->succeeded in a single request and produce at least one pages row linked via pages.source_job_id plus a job_items row pointing to that page.
- firecrawl_batch_scrape creates one jobs row with tool=firecrawl_batch_scrape and N job_items rows with kind=batch_target; firecrawl_check_batch_status reads jobs.status and aggregates job_items.status counts for that job.
- firecrawl_crawl creates one jobs row with tool=firecrawl_crawl and at least one job_items seed; discovered pages are appended as job_items(kind=crawl_page or discovered) with depth populated; firecrawl_check_crawl_status reads jobs.status and aggregates job_items.
- firecrawl_map creates one jobs row with tool=firecrawl_map and job_items rows with kind=discovered; map jobs should not create pages unless input specifies scraping; otherwise only url/title/description fields are populated.
- firecrawl_search creates one jobs row with tool=firecrawl_search; by default it stores SERP-like results as job_items(kind=serp_result, title, description, url). If input.scrapeOptions is present, each result may also create a pages row and link it via job_items.page_id.
- firecrawl_extract creates one jobs row with tool=firecrawl_extract and requires that either input.urls is provided (creating job_items) or input.page_id references an existing pages row in the same workspace; extraction output is stored in pages.extracted_data for the corresponding page(s).
- firecrawl_deep_research creates one jobs row with tool=firecrawl_deep_research; it may create child job_items(kind=research_source) pointing to pages produced by search/crawl steps, and it stores final synthesized findings in jobs.result_summary.
- firecrawl_generate_llmstxt creates one jobs row with tool=firecrawl_generate_llmstxt and must write generated content to pages.llms_txt for a page in the same workspace (creating the page artifact if necessary).
- Quota enforcement: on job completion, increment workspaces.pages_used by jobs.pages_fetched and workspaces.llm_tokens_used by jobs.llm_tokens_used; requests that would exceed monthly_page_limit or monthly_llm_token_limit must be rejected or forced into a failed job with error_code=quota_exceeded.
- FK integrity: job_items.job_id must reference an existing jobs row; job_items.page_id must reference an existing pages row in the same workspace as the job via jobs.workspace_id (enforced by application-level check).
- Status integrity: a jobs row cannot transition from succeeded/failed/cancelled to running; a job_items row cannot transition from succeeded/failed/skipped to any other status.
- Webhook delivery: if jobs.webhook_url is set, the system must attempt delivery exactly once per terminal job completion (succeeded/failed/cancelled) and record delivery metadata inside jobs.result_summary.webhook (attempted_at, status_code, error) without mutating terminal status.