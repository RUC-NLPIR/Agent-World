# Tavily MCP Server — local MCP environment

This backend stores web search and web content extraction requests made through the Tavily MCP Server, along with the resulting documents/snippets and extracted page content. The main workflows are: create a search request and persist ranked results; create an extract request for one or more URLs and persist the fetched/processed content plus any errors and usage/accounting.

Repository: https://github.com/StevenFengLi/tavily-mcp
Homepage: https://smithery.ai/server/@StevenFengLi/tavily-mcp

## Datastore

- `api_keys.json` — API keys (or MCP client credentials) used to authenticate requests and enforce quotas. In practice this maps to the upstream Tavily key, or a server-issued key that wraps the upstream key. (11 rows; fields: ['api_key_id', 'key_hash', 'key_prefix', 'label', 'status', 'quota_daily_requests', 'quota_daily_tokens', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked', 'suspended']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: quota_daily_requests >= 0
  - constraint: quota_daily_tokens >= 0
- `search_requests.json` — One invocation of the `tavily-search` tool. Since the MCP surface provides no parameters, the backend stores a raw input envelope plus inferred defaults and the resulting status/timing. (18 rows; fields: ['search_request_id', 'api_key_id', 'status', 'raw_input', 'normalized_query', 'options', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(api_key_id) on delete restrict
  - constraint: started_at is null iff status in ('queued')
  - constraint: finished_at is null iff status in ('queued','running')
  - constraint: error_code is not null iff status='failed'
- `search_results.json` — Ranked result items returned for a given search request (URLs, titles, snippets, and metadata). (37 rows; fields: ['search_result_id', 'search_request_id', 'rank', 'url', 'title', 'snippet', 'published_at', 'score', 'raw_result', 'created_at', 'updated_at'])
  - constraint: fk(search_request_id) references search_requests(search_request_id) on delete cascade
  - constraint: unique(search_request_id, rank)
  - constraint: unique(search_request_id, url)
  - constraint: rank >= 1
- `extract_requests.json` — One invocation of the `tavily-extract` tool. Stores the raw input (empty for current surface), server defaults, and aggregates over child extracted documents. (18 rows; fields: ['extract_request_id', 'api_key_id', 'status', 'raw_input', 'options', 'requested_url_count', 'succeeded_url_count', 'failed_url_count', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(api_key_id) on delete restrict
  - constraint: requested_url_count >= 0
  - constraint: succeeded_url_count >= 0
  - constraint: failed_url_count >= 0
- `extracted_documents.json` — Per-URL extraction outputs (raw HTML/text, cleaned content, metadata, and fetch/extraction diagnostics). (35 rows; fields: ['extracted_document_id', 'extract_request_id', 'url', 'final_url', 'status', 'http_status', 'content_type', 'raw_content', 'extracted_text', 'extracted_metadata', 'fetch_duration_ms', 'process_duration_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'processing', 'succeeded', 'failed', 'skipped']
  - constraint: fk(extract_request_id) references extract_requests(extract_request_id) on delete cascade
  - constraint: unique(extract_request_id, url)
  - constraint: http_status between 100 and 599 when not null
  - constraint: fetch_duration_ms >= 0 when not null

## Business rules enforced by the tools

- Every call to `tavily-search` must create exactly one row in search_requests and (on success) one or more rows in search_results linked by search_request_id.
- Every call to `tavily-extract` must create exactly one row in extract_requests and (when URLs exist) one row per URL in extracted_documents linked by extract_request_id.
- Requests may only be executed if api_keys.status='active' and the key has not exceeded quota_daily_requests for the current UTC day.
- The system must increment per-key usage by counting completed requests (status in ('succeeded','failed','cancelled')); queued/running do not count until terminal.
- Terminal statuses are immutable: once a request or extracted document is in succeeded/failed/cancelled/skipped, status cannot transition to a non-terminal state.
- On delete of an extract_request, all extracted_documents must be deleted (cascade). On delete of a search_request, all search_results must be deleted (cascade).
- If tool parameters are empty (current MCP schema), raw_input must still be stored as an object and options must be filled with server defaults to ensure reproducibility.
- For any failed entity (request or document), error_code must be set and error_message should be set; for any non-failed entity, error_code must be null.