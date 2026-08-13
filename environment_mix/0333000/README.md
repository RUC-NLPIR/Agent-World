# Open Library MCP Server — local MCP environment

This backend stores cached Open Library search requests and the book/work records returned for a given title query. The main workflow is: accept a title search, create a query record, fetch results from Open Library, persist works/editions/authors referenced by results, and return a normalized response from cached data when possible.

Repository: https://github.com/8enSmith/mcp-open-library
Homepage: https://smithery.ai/server/@8enSmith/mcp-open-library

## Datastore

- `api_keys.json` — API keys used to access this MCP server, with basic quota/rate-limit tracking to protect upstream Open Library and control abuse. (17 rows; fields: ['id', 'key_hash', 'label', 'status', 'daily_limit_requests', 'daily_used_requests', 'daily_window_started_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_limit_requests >= 0
  - constraint: daily_used_requests >= 0
- `title_search_queries.json` — Represents a single invocation of get_book_by_title(title), including normalization, caching metadata, and fetch lifecycle. (18 rows; fields: ['id', 'api_key_id', 'title_raw', 'title_normalized', 'status', 'requested_limit', 'upstream_url', 'upstream_http_status', 'upstream_etag', 'upstream_last_modified', 'error_code', 'error_message', 'fetched_at', 'cache_expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'succeeded', 'failed']
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: requested_limit >= 1 and requested_limit <= 100
  - constraint: length(title_raw) >= 1
  - constraint: unique(api_key_id, title_normalized, status) where status in ('queued','fetching')
- `ol_works.json` — Normalized Open Library Work entities cached locally to de-duplicate results across searches. (18 rows; fields: ['id', 'ol_work_key', 'title', 'first_publish_year', 'edition_count', 'cover_id', 'language_codes', 'subject_terms', 'status', 'raw_payload', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(ol_work_key)
  - constraint: first_publish_year is null or (first_publish_year >= 0 and first_publish_year <= 3000)
  - constraint: edition_count is null or edition_count >= 0
  - constraint: cover_id is null or cover_id >= 0
- `ol_authors.json` — Normalized Open Library Author entities cached locally and linked to works. (18 rows; fields: ['id', 'ol_author_key', 'name', 'status', 'raw_payload', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(ol_author_key)
- `title_query_results.json` — Join table linking a title search query to the ordered list of resulting works and the per-result metadata (score/fields) needed to reproduce responses. (18 rows; fields: ['id', 'query_id', 'work_id', 'rank', 'author_ids', 'publisher_names', 'publish_years', 'isbn10', 'isbn13', 'raw_doc', 'created_at', 'updated_at'])
  - lifecycle `rank`: []
  - constraint: foreign key (query_id) references title_search_queries(id) on delete cascade
  - constraint: foreign key (work_id) references ol_works(id) on delete restrict
  - constraint: unique(query_id, rank)
  - constraint: unique(query_id, work_id)

## Business rules enforced by the tools

- get_book_by_title(title) must create a title_search_queries row with title_raw = input title and title_normalized computed deterministically; title is required and must be non-empty after trimming.
- If there exists a title_search_queries row with the same title_normalized and status = 'succeeded' and cache_expires_at > now(), the service should return results from title_query_results (ordered by rank) without calling upstream.
- When a fetch begins, title_search_queries.status must transition queued -> fetching; on completion it must transition fetching -> succeeded or fetching -> failed. Direct transitions outside the lifecycle map are rejected.
- On a successful upstream fetch, the service must upsert ol_works by ol_work_key and ol_authors by ol_author_key, set last_seen_at = now() for touched entities, and insert/replace title_query_results rows for the query up to requested_limit.
- API key enforcement: requests are permitted only for api_keys.status = 'active'. Each successful tool call increments daily_used_requests; if daily_used_requests would exceed daily_limit_requests within the current daily window, the request must be rejected.
- Daily quota window: if now() - daily_window_started_at >= 24h, reset daily_used_requests to 0 and set daily_window_started_at = now() before counting the request.
- FK integrity: title_search_queries.api_key_id must exist; title_query_results.query_id and work_id must exist. Deleting a query deletes its results; works/authors cannot be deleted if referenced by any result rows (restrict).
- Data hygiene: requested_limit must be between 1 and 100 inclusive; rank must be >= 1; upstream_http_status if set must be between 100 and 599; numeric identifiers like cover_id must be non-negative.