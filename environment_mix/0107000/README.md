# SERP API Server — local MCP environment

This backend powers a SERP analysis and keyword/competitor research API. It stores API clients (keys), tracks each analysis request as a job, persists normalized SERP snapshots and derived keyword/competitor insights, and enforces quotas/rate limits for production usage.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@itsanamune/seo-mcp

## Datastore

- `api_keys.json` — API credentials representing a client/app using the SERP API Server, including status and quota policy. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'owner_name', 'owner_email', 'status', 'plan', 'daily_request_limit', 'daily_serp_fetch_limit', 'concurrency_limit', 'allowed_engines', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: daily_request_limit >= 0
  - constraint: daily_serp_fetch_limit >= 0
- `usage_daily.json` — Daily usage counters per API key used to enforce quotas for all tools. (23 rows; fields: ['id', 'api_key_id', 'usage_date', 'requests_total', 'serp_fetches_total', 'jobs_started_total', 'jobs_succeeded_total', 'jobs_failed_total', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'sealed']
  - constraint: unique(api_key_id, usage_date)
  - constraint: requests_total >= 0
  - constraint: serp_fetches_total >= 0
  - constraint: jobs_started_total >= 0
- `analysis_jobs.json` — Core request/job record for each tool invocation (analyze_serp, research_keywords, analyze_competitors) including inputs, lifecycle, and output pointers. (35 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'idempotency_key', 'input', 'engine', 'query_text', 'target_domain', 'locale', 'location', 'device', 'requested_at', 'started_at', 'finished_at', 'error_code', 'error_message', 'output', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: index(api_key_id, requested_at)
  - constraint: index(tool_name, status)
  - constraint: unique(api_key_id, idempotency_key) where idempotency_key is not null
  - constraint: finished_at is null OR started_at is not null
- `serp_snapshots.json` — Stored SERP snapshot data produced by analyze_serp jobs, including raw response and normalized top results metadata. (22 rows; fields: ['id', 'analysis_job_id', 'engine', 'query_text', 'locale', 'location', 'device', 'fetched_at', 'raw_serp', 'results', 'serp_features', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'purged']
  - constraint: unique(analysis_job_id)
  - constraint: engine <> ''
  - constraint: query_text <> ''
  - constraint: array_length(results) >= 0
- `keyword_insights.json` — Keyword research outputs produced by research_keywords jobs, including related keywords and metrics. (17 rows; fields: ['id', 'analysis_job_id', 'seed', 'engine', 'locale', 'location', 'keywords', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'purged']
  - constraint: unique(analysis_job_id)
  - constraint: seed <> ''
  - constraint: array_length(keywords) >= 0
- `competitor_insights.json` — Competitor analysis outputs produced by analyze_competitors jobs, including competing domains/URLs and overlap metrics. (15 rows; fields: ['id', 'analysis_job_id', 'input_keyword', 'input_domain', 'engine', 'locale', 'location', 'competitors', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'purged']
  - constraint: unique(analysis_job_id)
  - constraint: (input_keyword is not null) OR (input_domain is not null)
  - constraint: array_length(competitors) >= 0

## Business rules enforced by the tools

- Each tool invocation creates an analysis_jobs row with tool_name set accordingly; '_health' may short-circuit by directly creating a succeeded job with minimal output.
- Requests must be authenticated by an api_keys record with status='active'; suspended or revoked keys are rejected and must not create jobs.
- For each accepted request, usage_daily.requests_total is incremented; if the request will perform an upstream SERP fetch, usage_daily.serp_fetches_total is incremented before executing the fetch (to prevent race-condition overages).
- A request must be rejected if usage_daily.requests_total would exceed api_keys.daily_request_limit for the current UTC day.
- A job that triggers upstream SERP retrieval must be rejected if usage_daily.serp_fetches_total would exceed api_keys.daily_serp_fetch_limit for the current UTC day.
- A request must be rejected if the number of jobs in status IN ('queued','running') for the api_key_id is >= api_keys.concurrency_limit.
- Idempotency: if (api_key_id, idempotency_key) matches an existing analysis_jobs row, return the existing job/output and do not create a new job.
- Status transitions must follow the declared lifecycle; in particular, a job cannot move from succeeded/failed/cancelled back to running/queued.
- analyze_serp jobs that succeed must create exactly one serp_snapshots row linked by analysis_job_id; research_keywords jobs that succeed must create exactly one keyword_insights row; analyze_competitors jobs that succeed must create exactly one competitor_insights row.
- Purging: setting serp_snapshots/keyword_insights/competitor_insights status to 'purged' must also remove or null out large raw payload fields (raw_serp/results/keywords/competitors) to satisfy retention policies while keeping minimal audit metadata.
- FK integrity: deleting an api_keys row is not allowed if referenced by analysis_jobs or usage_daily; keys should be revoked instead.
- For analyze_competitors, at least one of input_keyword or input_domain must be provided in analysis_jobs.input and mirrored into competitor_insights; backend must validate this even though the public tool schema shows no parameters.