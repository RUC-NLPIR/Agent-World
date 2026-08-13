# Decodo MCP Server — local MCP environment

This backend supports a scraping/search-aggregation service that can fetch a URL as markdown and run parsed search scrapes against Google and Amazon. It stores workspaces and API keys for access control, submitted scrape/search jobs, normalized parsed result items, and request/usage logs for quota and abuse prevention.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@Decodo/decodo-mcp-server

## Datastore

- `workspaces.json` — Tenant container for API usage, billing/quota, and logical isolation of jobs/results. (18 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_request_quota', 'monthly_byte_quota', 'max_concurrent_jobs', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_request_quota >= 0
  - constraint: monthly_byte_quota >= 0
  - constraint: max_concurrent_jobs >= 1
- `api_keys.json` — API credentials used by clients to authenticate and authorize tool calls to the service. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
- `jobs.json` — Submitted scrape/search jobs representing calls to scrape_as_markdown, google_search_parsed, and amazon_search_parsed. Stores request metadata, execution state, and output pointers. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'request_parameters', 'input_url', 'input_query', 'locale', 'result_markdown', 'result_raw', 'http_status_code', 'error_code', 'error_message', 'attempt_count', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: attempt_count >= 0
  - constraint: http_status_code is null or (http_status_code >= 100 and http_status_code <= 599)
  - constraint: tool_name in ('scrape_as_markdown','google_search_parsed','amazon_search_parsed')
  - constraint: ((tool_name = 'scrape_as_markdown') implies (input_url is not null))
- `parsed_results.json` — Normalized parsed items produced by google_search_parsed and amazon_search_parsed, stored as row-per-result for filtering, pagination, and analytics. (18 rows; fields: ['id', 'job_id', 'workspace_id', 'engine', 'rank', 'title', 'url', 'snippet', 'source', 'asin', 'product_name', 'price_amount', 'price_currency', 'rating_value', 'rating_count', 'raw_item', 'created_at', 'updated_at'])
  - lifecycle `engine`: ['google', 'amazon']
  - constraint: unique(job_id, rank)
  - constraint: rank >= 1
  - constraint: price_amount is null or price_amount >= 0
  - constraint: rating_value is null or (rating_value >= 0 and rating_value <= 5)
- `request_logs.json` — Immutable per-call log used for auditing, quota enforcement, latency tracking, and abuse detection. A row is written for each tool invocation. (20 rows; fields: ['id', 'workspace_id', 'api_key_id', 'job_id', 'tool_name', 'request_parameters', 'response_status', 'http_status_code', 'latency_ms', 'bytes_downloaded', 'result_item_count', 'client_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `response_status`: ['ok', 'error', 'rejected_quota', 'rejected_auth', 'rejected_validation']
  - constraint: http_status_code >= 100 and http_status_code <= 599
  - constraint: bytes_downloaded >= 0
  - constraint: result_item_count >= 0
  - constraint: latency_ms is null or latency_ms >= 0

## Business rules enforced by the tools

- Every tool invocation MUST authenticate with an active api_keys row; revoked keys MUST be rejected and logged with response_status='rejected_auth' and job_id=null.
- A workspace in status='suspended' or 'deleted' MUST NOT create new jobs; requests MUST be rejected and logged.
- Before creating a job, the system MUST enforce workspace monthly_request_quota and monthly_byte_quota based on request_logs within the current calendar month; if exceeded, reject with response_status='rejected_quota' and do not create a job.
- For scrape_as_markdown, jobs.input_url MUST be a non-empty absolute URL; for google_search_parsed and amazon_search_parsed, jobs.input_query MUST be non-empty. Invalid inputs MUST be rejected with response_status='rejected_validation' and no job created.
- The number of jobs in status in ('queued','running') per workspace MUST NOT exceed workspaces.max_concurrent_jobs; if it would, new requests MUST either be queued only if within limit or rejected with response_status='rejected_quota' (capacity).
- When a job transitions to status='succeeded', finished_at MUST be set and (tool_name='scrape_as_markdown' implies result_markdown is not null) and (tool_name in ('google_search_parsed','amazon_search_parsed') implies at least one parsed_results row may exist and jobs.result_raw may be set).
- parsed_results rows MUST only be created for jobs where tool_name is google_search_parsed (engine='google') or amazon_search_parsed (engine='amazon'); attempts to insert mismatched engine/tool MUST be rejected.
- request_logs MUST be written for every tool call regardless of outcome; bytes_downloaded and result_item_count MUST be 0 for rejected_auth/rejected_quota/rejected_validation outcomes.
- API keys MUST be unique per workspace by name, and secrets MUST only be stored as key_hash; plaintext keys MUST never be persisted.