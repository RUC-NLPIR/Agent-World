# Oxylabs MCP — local MCP environment

This backend stores customers (workspaces) and their API credentials, accepts scrape/search jobs for multiple providers (Universal, Google Search, Amazon Search, Amazon Product), and persists job inputs, execution state, and outputs. The main workflow is: an authenticated client submits a scraper job, the system schedules/executes it, tracks lifecycle and usage, and stores result payloads for retrieval/traceability and billing/quota enforcement.

Repository: https://github.com/oxylabs/oxylabs-mcp
Homepage: https://smithery.ai/server/@oxylabs/oxylabs-mcp

## Datastore

- `workspaces.json` — Tenant accounts representing a customer/project. Owns API keys, jobs, and usage/billing configuration. (12 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_job_quota', 'monthly_request_quota', 'max_concurrent_jobs', 'default_locale', 'default_geo', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: monthly_job_quota >= 0
  - constraint: monthly_request_quota >= 0
  - constraint: max_concurrent_jobs >= 1
- `api_keys.json` — API credentials for authenticating requests to the MCP service. Keys are scoped to a workspace and can be rotated/revoked. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
- `scrape_jobs.json` — A submitted scraping/search task corresponding to one of the MCP tools. Stores normalized parameters, execution state, and billing-relevant metadata. (20 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool', 'status', 'priority', 'scheduled_at', 'started_at', 'finished_at', 'idempotency_key', 'request_fingerprint', 'input', 'input_url', 'input_query', 'target_domain', 'geo', 'locale', 'user_agent_type', 'pagination_page', 'pagination_pages', 'output_format', 'parse_content', 'amazon_category_id', 'amazon_merchant_id', 'amazon_currency', 'amazon_asin', 'amazon_auto_select_variant', 'attempt', 'max_attempts', 'error_code', 'error_message', 'billable_units', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key (api_key_id) references api_keys(id) on delete set null
  - constraint: unique(workspace_id, idempotency_key) where idempotency_key is not null
  - constraint: priority between 0 and 100
- `job_results.json` — Result payloads produced by scrape jobs, including raw and parsed content plus extracted SERP/product data. Supports multi-page pagination by storing multiple result parts per job. (19 rows; fields: ['id', 'job_id', 'part_index', 'status', 'http_status', 'final_url', 'content_type', 'raw_body', 'parsed', 'output_format', 'bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'redacted', 'deleted']
  - constraint: foreign key (job_id) references scrape_jobs(id) on delete cascade
  - constraint: unique(job_id, part_index)
  - constraint: part_index >= 0
  - constraint: http_status is null or http_status between 100 and 599
- `usage_ledger.json` — Append-only billing and quota ledger recording billable units for each job and optional per-request granularity for audits and rate limiting. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'job_id', 'tool', 'units', 'unit_type', 'period_yyyymm', 'created_at', 'updated_at'])
  - lifecycle `unit_type`: ['request', 'page', 'job', 'byte']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key (api_key_id) references api_keys(id) on delete set null
  - constraint: foreign key (job_id) references scrape_jobs(id) on delete set null
  - constraint: units >= 0

## Business rules enforced by the tools

- All tool invocations (universal_scraper, google_search_scraper, amazon_search_scraper, amazon_product_scraper) create exactly one scrape_jobs row with tool set accordingly and input containing the raw normalized parameters for that invocation, even if the vendor tool schema is empty.
- A request must authenticate with an active api_keys row whose workspace is in status=active; otherwise the request is rejected and no scrape_jobs row is created.
- Idempotency: if (workspace_id, idempotency_key) already exists, the service returns the existing scrape_jobs record instead of creating a new one.
- Quota enforcement: creating a new job is rejected if the workspace has already recorded monthly_job_quota jobs in the current period_yyyymm or monthly_request_quota units in usage_ledger for the same period_yyyymm (unless plan=enterprise and quotas are configured as very large values).
- Concurrency enforcement: a workspace cannot transition more than max_concurrent_jobs jobs into status=running at once; scheduler must keep excess jobs queued.
- Status transitions must follow scrape_jobs.lifecycle.transitions; in particular succeeded/failed/cancelled/expired are terminal states except failed may be retried by transitioning back to queued and incrementing attempt, provided attempt < max_attempts.
- For amazon_product_scraper jobs, amazon_asin is required; for google_search_scraper and amazon_search_scraper jobs, input_query is required; for universal_scraper jobs, at least one of input_url or input_query must be present after normalization.
- If parse_content=false, job_results.parsed must be null; if parse_content=true, job_results.parsed may be populated based on tool-specific extraction.
- Pagination: when pagination_pages > 1, the system creates one job_results row per fetched page with unique (job_id, part_index) where part_index increments from 0; billable units must increase by at least 1 unit_type=page per additional page fetched.
- On job completion (succeeded or failed), scrape_jobs.billable_units must equal the sum of usage_ledger.units for that job_id where unit_type in ('request','page','job','byte') according to internal pricing rules.
- Job results are retained while job_results.status=ready; administrative actions may transition to redacted or deleted, after which raw_body must be nulled and bytes may be set to 0 for deleted records.
- FK integrity is enforced: a job cannot exist without a workspace; results cannot exist without a job; deleting a workspace cascades to jobs and results, and deletes/voids associated usage_ledger rows by FK behavior (set null for job_id where required).