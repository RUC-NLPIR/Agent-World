# Web Research Server — local MCP environment

This backend stores Google search queries, their result sets, and webpage visits used to extract content and optionally capture screenshots. The main workflows are: create a search request and persist ranked results; create a page visit record to fetch and store extracted text/metadata; and create screenshot artifacts linked to a visit (or to the latest active visit session).

Repository: https://github.com/chuanmingliu/mcp-webresearch
Homepage: https://smithery.ai/server/@chuanmingliu/mcp-webresearch

## Datastore

- `search_queries.json` — Persistent record of Google searches initiated via the API. (19 rows; fields: ['id', 'query', 'normalized_query', 'status', 'provider', 'result_count', 'error_message', 'started_at', 'finished_at', 'request_fingerprint', 'request_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: provider = 'google'
  - constraint: char_length(query) between 1 and 2048
  - constraint: char_length(normalized_query) between 1 and 2048
  - constraint: result_count >= 0
- `search_results.json` — Ranked search results returned for a given search query. (17 rows; fields: ['id', 'search_query_id', 'rank', 'title', 'url', 'display_url', 'snippet', 'provider_result_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: rank >= 1 and rank <= 100
  - constraint: char_length(url) between 1 and 4096
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, url)
- `page_visits.json` — A visit/fetch of a web page with extracted content and optional screenshot capture intent. (19 rows; fields: ['id', 'source_search_query_id', 'source_search_result_id', 'url', 'final_url', 'take_screenshot', 'status', 'http_status', 'content_type', 'content_length_bytes', 'title', 'extracted_text', 'extracted_html', 'extraction_metadata', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'extracting', 'succeeded', 'failed', 'cancelled']
  - constraint: char_length(url) between 1 and 4096
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: content_length_bytes is null or content_length_bytes >= 0
  - constraint: source_search_result_id is null or source_search_query_id is not null
- `screenshots.json` — Screenshot artifacts captured during/after a page visit; also supports on-demand capture of the current page. (19 rows; fields: ['id', 'page_visit_id', 'status', 'image_format', 'storage_backend', 'storage_key', 'byte_size', 'width_px', 'height_px', 'captured_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'capturing', 'stored', 'failed']
  - constraint: char_length(storage_key) between 1 and 2048
  - constraint: byte_size is null or byte_size > 0
  - constraint: width_px is null or width_px > 0
  - constraint: height_px is null or height_px > 0
- `browser_sessions.json` — Tracks the 'current page' concept needed by take_screenshot; represents an automation/browser context with an active URL/visit. (18 rows; fields: ['id', 'status', 'current_page_visit_id', 'current_url', 'last_activity_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closing', 'closed', 'errored']
  - constraint: current_page_visit_id is null or status in ('active','closing')
  - constraint: char_length(current_url) <= 4096
  - constraint: last_activity_at <= now() + interval '5 minutes' (guard against clock skew; enforced at app layer if needed)

## Business rules enforced by the tools

- search_google(query) must create a search_queries row with provider='google' and status transitioning queued->running->(succeeded|failed), and must insert 0..100 search_results rows linked by search_query_id.
- search_results for a given search_query_id must have unique rank and unique url; ranks must start at 1 and be contiguous if the provider returns a full page (contiguity enforced at app layer).
- visit_page(url, takeScreenshot) must create a page_visits row and transition status queued->fetching->extracting->(succeeded|failed); extracted_text may be null only if status != 'succeeded'.
- If visit_page is initiated from a search result, the backend must set source_search_query_id and source_search_result_id and verify the referenced search_results.search_query_id matches source_search_query_id.
- If page_visits.take_screenshot = true and the visit succeeds, the service must enqueue at least one screenshots row linked to that page_visit_id (queued->capturing->stored or failed).
- take_screenshot() must create a screenshots row whose page_visit_id is the browser_sessions.current_page_visit_id for an active session; if no active session/current page exists, the call must fail with a deterministic error and create no screenshot row (or create one with status='failed' and an error_message, but behavior must be consistent).
- Only one browser_sessions row may be 'active' per runtime instance/tenant context; if multiple contexts exist, the uniqueness must be enforced by an app-level lock key (e.g., unique(active_session_key) where status='active').
- All status transitions must follow the declared lifecycle graphs; direct transitions not listed must be rejected.
- URLs stored in search_results.url and page_visits.url must be absolute URLs with http/https scheme (validated at app layer).
- Retention/quota: screenshots.byte_size summed over stored screenshots for a given time window must not exceed a configured limit per instance; on exceeding, new screenshots must be rejected or older artifacts must be deleted according to policy (enforced at app layer).