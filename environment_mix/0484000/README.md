# Google Scholar Search Server — local MCP environment

This backend powers a Google Scholar-like search API by recording search requests, returned publication results, and author profile lookups. Main workflows are: (1) accept a keyword/advanced search request, execute it, store the result set for retrieval/analytics; (2) accept an author info request, fetch/refresh the author profile and store it for reuse and rate-limiting.

Repository: https://github.com/DeadWaveWave/Google-Scholar-MCP-Server
Homepage: https://smithery.ai/server/@DeadWaveWave/google-scholar-mcp-server

## Datastore

- `api_keys.json` — API keys used to authenticate callers and enforce basic quotas/rate limits for Scholar search and author lookups. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'requests_per_minute_limit', 'requests_per_day_limit', 'requests_today', 'day_window_start', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit >= 1
  - constraint: requests_per_day_limit >= 1
  - constraint: requests_today >= 0
- `scholar_searches.json` — A single search request to Google Scholar, either keyword or advanced, including parameters and execution metadata. (18 rows; fields: ['id', 'api_key_id', 'search_type', 'query', 'author', 'year_start', 'year_end', 'num_results_requested', 'status', 'executed_at', 'completed_at', 'http_status', 'error_code', 'error_message', 'result_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: num_results_requested between 1 and 50
  - constraint: result_count >= 0
  - constraint: year_start is null or (year_start between 1600 and 2200)
- `scholar_publications.json` — Canonical publication records de-duplicated across searches (papers, articles, books) as identified from Google Scholar results. (19 rows; fields: ['id', 'scholar_cluster_id', 'title', 'authors_text', 'publication_venue', 'year', 'snippet', 'cited_by_count', 'url', 'pdf_url', 'source', 'status', 'first_seen_at', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(scholar_cluster_id) where scholar_cluster_id is not null
  - constraint: cited_by_count is null or cited_by_count >= 0
  - constraint: year is null or (year between 1600 and 2200)
- `search_results.json` — Join table storing ordered publication hits for a specific search request, including per-hit fields that can vary by query (rank, snippet). (19 rows; fields: ['id', 'search_id', 'publication_id', 'rank', 'snippet_override', 'raw_result', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: foreign key(search_id) references scholar_searches(id) on delete cascade
  - constraint: foreign key(publication_id) references scholar_publications(id) on delete restrict
  - constraint: unique(search_id, rank)
  - constraint: unique(search_id, publication_id)
- `author_profiles.json` — Cached author profiles returned by the author info tool, keyed by normalized author name (and optionally an upstream Scholar author id if discovered). (18 rows; fields: ['id', 'normalized_name', 'display_name', 'scholar_author_id', 'affiliation', 'interests', 'cited_by_total', 'h_index', 'i10_index', 'profile_url', 'status', 'fetched_at', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'failed']
  - constraint: unique(normalized_name)
  - constraint: unique(scholar_author_id) where scholar_author_id is not null
  - constraint: cited_by_total is null or cited_by_total >= 0
  - constraint: h_index is null or h_index >= 0

## Business rules enforced by the tools

- For search_google_scholar_key_words: create a scholar_searches row with search_type='keywords', query set from input, author/year_start/year_end null, num_results_requested from input (default 5), then execute and persist up to num_results_requested rows in search_results linked to scholar_publications.
- For search_google_scholar_advanced: create a scholar_searches row with search_type='advanced', query set from input, author set from input if non-null, year_range if provided must have exactly 2 integers mapping to year_start/year_end, num_results_requested from input (default 5), then execute and persist results as above.
- num_results must be clamped/enforced to 1..50; any request outside this range must be rejected or normalized consistently (service policy).
- If year_range is provided, both bounds are required and must satisfy 1600 <= year_start <= year_end <= 2200; otherwise the request is rejected.
- A scholar_searches row must transition status queued -> running -> (succeeded|failed|cancelled); completed_at must be set when entering a terminal state; executed_at must be set when entering running.
- On succeeded searches: result_count must equal the count of search_results rows for that search_id; on failed/cancelled searches: result_count must be 0 and no search_results rows may exist.
- Publication de-duplication: if an upstream scholar_cluster_id is present, results must upsert into scholar_publications by scholar_cluster_id; otherwise may insert a new publication row (optionally de-dupe by normalized title+year).
- For get_author_info: look up author_profiles by normalized_name; if status is fresh and fetched_at is within cache TTL, return cached data; otherwise fetch from upstream and update the same row, setting status to fresh on success or failed on error.
- API key enforcement: requests are allowed only for api_keys.status='active'; each successful tool call increments requests_today and must not exceed requests_per_day_limit; per-minute throttling must respect requests_per_minute_limit.
- FK integrity: deleting an api_key is restricted if it has scholar_searches; deleting a scholar_searches cascades to search_results; scholar_publications cannot be deleted while referenced by search_results.