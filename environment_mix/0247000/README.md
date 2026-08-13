# DuckDuckGo Search Server — local MCP environment

This backend powers a DuckDuckGo-backed search API that logs search requests and their returned SERP items, and can fetch and parse webpage content for a given URL. Core workflows are: (1) accept a search query with a max_results limit, call the upstream provider, persist the request and normalized results, and return formatted output; (2) fetch a URL, store fetch attempts and extracted content metadata for reuse and auditing.

Repository: https://github.com/nickclyde/duckduckgo-mcp-server
Homepage: https://smithery.ai/server/@nickclyde/duckduckgo-mcp-server

## Datastore

- `api_clients.json` — Identifies the calling client/application (or installation) and stores quota/abuse-control settings used by the service when handling search and fetch_content requests. (32 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'rate_limit_per_minute', 'daily_request_quota', 'daily_reset_at', 'requests_today', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: rate_limit_per_minute between 1 and 6000
  - constraint: daily_request_quota between 0 and 1000000
  - constraint: requests_today >= 0
- `search_queries.json` — A log of each DuckDuckGo search request made through the service, including the query string and requested max_results, along with execution metadata. (32 rows; fields: ['id', 'client_id', 'query', 'max_results', 'status', 'provider', 'error_message', 'result_count', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: length(query) between 1 and 2000
  - constraint: max_results between 1 and 50
  - constraint: result_count is null or result_count >= 0
- `search_results.json` — Normalized SERP items returned for a given search query. Stores rank/order and key fields needed to format results and optionally drive later fetch_content calls. (30 rows; fields: ['id', 'search_query_id', 'rank', 'title', 'url', 'display_url', 'snippet', 'provider_result_id', 'created_at', 'updated_at'])
  - constraint: fk(search_query_id) references search_queries(id) on delete cascade
  - constraint: unique(search_query_id, rank)
  - constraint: rank between 1 and 50
  - constraint: length(url) between 1 and 4000
- `url_documents.json` — Canonical representation of a URL that may be fetched and parsed. Supports deduplication and reuse of fetch results across multiple requests. (30 rows; fields: ['id', 'canonical_url', 'url_hash', 'first_seen_at', 'last_fetched_at', 'created_at', 'updated_at'])
  - constraint: unique(url_hash)
  - constraint: length(canonical_url) between 1 and 4000
- `content_fetches.json` — Each attempt to fetch and parse webpage content for a URL. Stores response metadata and extracted content for returning to callers and for caching. (38 rows; fields: ['id', 'client_id', 'url_document_id', 'requested_url', 'status', 'http_status', 'final_url', 'content_type', 'content_length_bytes', 'extracted_text', 'extracted_title', 'error_message', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'parsing', 'succeeded', 'failed']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: fk(url_document_id) references url_documents(id) on delete restrict
  - constraint: length(requested_url) between 1 and 4000
  - constraint: http_status is null or http_status between 100 and 599

## Business rules enforced by the tools

- Tool search must create a search_queries row with query and max_results, enforce max_results default=10 and clamp/validate to [1,50].
- Tool search must transition search_queries.status queued->running->(succeeded|failed) and persist search_results rows with ranks starting at 1; it must set search_queries.result_count to the number of persisted results.
- Tool fetch_content must normalize the provided url into url_documents.canonical_url and upsert url_documents by url_hash; it must store the original user input in content_fetches.requested_url.
- Tool fetch_content must create a content_fetches row and transition status queued->fetching->parsing->(succeeded|failed); on success it should update url_documents.last_fetched_at.
- Rate limiting/quota: for any tool call, the service must reject requests when api_clients.status != 'active', when requests_today >= daily_request_quota (unless quota=0 meaning no requests allowed), or when per-minute rate limiting would be exceeded; accepted calls increment requests_today atomically.
- Caching policy: if a recent succeeded content_fetches exists for the same url_document_id within a configured TTL, the service may return the stored extracted_text/extracted_title without performing a new fetch, but must still record a new content_fetches row marked succeeded with a reference to the reused content (or store extracted_text again) according to operator policy.
- URL integrity: url_documents.canonical_url must be a valid absolute URL with http/https scheme; other schemes must be rejected or marked failed in content_fetches with an error_message.
- FK integrity must be enforced: deleting a search_queries row must cascade delete its search_results; deleting an api_client must be prevented if it has queries or fetches.