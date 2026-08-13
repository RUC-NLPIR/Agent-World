# Serper Search and Scrape — local MCP environment

This backend supports a Serper-powered Google Search and web scraping service, storing authenticated clients, their search/scrape jobs, and the returned artifacts (SERP items and scraped page content). Core workflows are: accept a request (with an API key), execute against the Serper provider, persist results for replay/auditing, and enforce per-key quotas and lifecycle status transitions.

Repository: https://github.com/marcopesani/mcp-server-serper
Homepage: https://smithery.ai/server/@marcopesani/mcp-server-serper

## Datastore

- `api_keys.json` — API keys used to authenticate callers and enforce quota/rate limits for search and scrape operations. (17 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'plan', 'quota_search_per_day', 'quota_scrape_per_day', 'rate_limit_per_minute', 'usage_day', 'usage_search_count', 'usage_scrape_count', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, created_at)
  - constraint: quota_search_per_day >= 0
  - constraint: quota_scrape_per_day >= 0
- `search_queries.json` — Represents a single google_search job executed (or attempted) against the Serper provider, including stored request and normalized response metadata. (18 rows; fields: ['id', 'api_key_id', 'status', 'request_params', 'query_text', 'provider', 'provider_request_id', 'http_status', 'error_code', 'error_message', 'result_count', 'cost_units', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys.id on delete restrict
  - constraint: result_count >= 0
  - constraint: cost_units >= 0
  - constraint: http_status between 100 and 599 when not null
- `search_results.json` — Normalized SERP items returned for a google_search job, across result types (organic, news, images, etc.). (18 rows; fields: ['id', 'search_query_id', 'position', 'result_type', 'title', 'url', 'display_url', 'snippet', 'source', 'published_at', 'raw_item', 'created_at', 'updated_at'])
  - constraint: fk(search_query_id) references search_queries.id on delete cascade
  - constraint: unique(search_query_id, position, result_type)
  - constraint: position >= 1
- `scrape_jobs.json` — Represents a single scrape request. Stores raw request parameters and execution outcome, optionally linked to a search result URL. (19 rows; fields: ['id', 'api_key_id', 'status', 'request_params', 'url', 'linked_search_result_id', 'http_status', 'content_type', 'content_bytes', 'extracted_text', 'extracted_html', 'raw_response', 'error_code', 'error_message', 'cost_units', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys.id on delete restrict
  - constraint: fk(linked_search_result_id) references search_results.id on delete set null
  - constraint: http_status between 100 and 599 when not null
  - constraint: content_bytes >= 0
- `request_logs.json` — Append-only audit log of tool invocations (google_search and scrape), including request/response payloads for debugging and compliance, correlated to the persisted job rows. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'search_query_id', 'scrape_job_id', 'request_payload', 'response_payload', 'error_payload', 'latency_ms', 'client_ip', 'user_agent', 'created_at', 'updated_at'])
  - constraint: fk(api_key_id) references api_keys.id on delete restrict
  - constraint: fk(search_query_id) references search_queries.id on delete set null
  - constraint: fk(scrape_job_id) references scrape_jobs.id on delete set null
  - constraint: latency_ms >= 0

## Business rules enforced by the tools

- Every google_search invocation must create exactly one search_queries row and at least one request_logs row referencing it.
- Every scrape invocation must create exactly one scrape_jobs row and at least one request_logs row referencing it.
- Requests authenticated with an api_keys.status not equal to 'active' must be rejected and must not create search_queries/scrape_jobs rows; they may create a request_logs row with error_payload.
- For each api_key_id and usage_day, usage_search_count must not exceed quota_search_per_day and usage_scrape_count must not exceed quota_scrape_per_day; increments occur only when a job transitions to 'running' (or on 'succeeded' if the implementation is strictly success-billed), but must be consistent across both tools.
- Rate limiting must enforce api_keys.rate_limit_per_minute across both tools combined; violations must be logged in request_logs.error_payload.
- A search_queries row may only transition status according to its declared lifecycle transitions; same for scrape_jobs.
- search_results rows may only be inserted for search_queries with status in ('running','succeeded'); once the parent query is 'succeeded', result rows are immutable except for redaction updates to raw_item fields.
- If scrape_jobs.linked_search_result_id is set, then scrape_jobs.url (if not null) must equal search_results.url for the referenced result, or url must be null and derived from the linked search result at execution time.
- Deletion of a search_queries row must cascade delete its search_results; api_keys rows must be delete-restricted while referenced by any search_queries, scrape_jobs, or request_logs.
- Because tool parameter schemas are empty, request_params/request_payload must accept arbitrary JSON objects, but must be capped by a maximum size (e.g., 64KB) and validated to be JSON objects (not arrays/primitives).
- Stored extracted_html and extracted_text must be size-limited (e.g., 2MB each); if larger, the implementation must truncate and record truncation info inside raw_response or error_payload.