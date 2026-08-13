# Google Scholar Search Server — local MCP environment

This backend powers a Google Scholar search server that accepts keyword and advanced (author/year-range) queries, executes scraping/search jobs, and persists normalized publication results. It also supports an author-lookup workflow that stores resolved author profiles and their publication lists for faster subsequent requests and rate-limit control.

Repository: https://github.com/jiqingci/google
Homepage: https://smithery.ai/server/@jiqingci/google

## Datastore

- `api_keys.json` — API credentials used to authenticate clients and enforce per-key quotas/rate limits for Scholar search and author info lookups. (31 rows; fields: ['id', 'key_hash', 'label', 'status', 'daily_request_limit', 'daily_requests_used', 'daily_window_start_at', 'max_num_results_per_query', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_request_limit >= 0
  - constraint: daily_requests_used >= 0
  - constraint: max_num_results_per_query between 1 and 50000
- `search_requests.json` — A persisted record of each keyword/advanced search invocation, its parameters, execution status, and summary results metadata. (32 rows; fields: ['id', 'api_key_id', 'tool_name', 'query', 'author', 'year_start', 'year_end', 'year_range_raw', 'num_results_requested', 'num_results_returned', 'status', 'error_code', 'error_message', 'source', 'requested_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'partial']
  - constraint: foreign key(api_key_id) references api_keys(id)
  - constraint: num_results_requested between 1 and 50000
  - constraint: num_results_returned >= 0
  - constraint: year_start is null or (year_start between 1500 and 2100)
- `publications.json` — Canonical deduplicated publication records extracted from Scholar results (title, venue, year, identifiers, citation counts). (35 rows; fields: ['id', 'scholar_cluster_id', 'title', 'normalized_title', 'publication_year', 'venue', 'authors_text', 'abstract_snippet', 'url', 'pdf_url', 'cited_by_count', 'status', 'merged_into_publication_id', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'merged', 'tombstoned']
  - constraint: unique(scholar_cluster_id) where scholar_cluster_id is not null
  - constraint: cited_by_count >= 0
  - constraint: publication_year is null or (publication_year between 1500 and 2100)
  - constraint: status in ('active','merged','tombstoned')
- `search_results.json` — Join table between search requests and publications, storing rank/order and per-request extracted attributes. (29 rows; fields: ['id', 'search_request_id', 'publication_id', 'rank', 'result_type', 'snippet', 'captured_at', 'created_at', 'updated_at'])
  - lifecycle `result_type`: ['organic', 'citation', 'patent', 'book', 'unknown']
  - constraint: foreign key(search_request_id) references search_requests(id) on delete cascade
  - constraint: foreign key(publication_id) references publications(id)
  - constraint: unique(search_request_id, rank)
  - constraint: unique(search_request_id, publication_id)
- `author_profiles.json` — Resolved author profiles for get_author_info, including Scholar author id/handle when discoverable and summary metrics. (30 rows; fields: ['id', 'display_name', 'normalized_name', 'scholar_author_id', 'affiliation', 'email_domain', 'interests', 'cited_by_total', 'h_index', 'i10_index', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'not_found', 'blocked']
  - constraint: unique(scholar_author_id) where scholar_author_id is not null
  - constraint: unique(normalized_name)
  - constraint: cited_by_total >= 0
  - constraint: h_index >= 0
- `author_publications.json` — Join table connecting author profiles to canonical publications, preserving per-author ordering and authorship position when available. (33 rows; fields: ['id', 'author_profile_id', 'publication_id', 'authorship_position', 'is_corresponding', 'sort_order', 'added_at', 'created_at', 'updated_at'])
  - lifecycle `is_corresponding`: [False, True]
  - constraint: foreign key(author_profile_id) references author_profiles(id) on delete cascade
  - constraint: foreign key(publication_id) references publications(id)
  - constraint: unique(author_profile_id, publication_id)
  - constraint: authorship_position is null or authorship_position >= 1

## Business rules enforced by the tools

- Each tool invocation must authenticate with an api_keys record in status='active'; otherwise reject the request.
- For both search tools, num_results must be between 1 and min(50000, api_keys.max_num_results_per_query); requests outside this range are rejected.
- For search_google_scholar_key_words, author/year_range inputs are not accepted; persisted search_requests.tool_name must be 'search_google_scholar_key_words' and author/year_start/year_end must be NULL.
- For search_google_scholar_advanced, author may be NULL; if year_range is provided, it must be an array of length 2 with integer years, and year_start <= year_end.
- Creating a search request inserts a row in search_requests with status='queued' and requested_at=now(); a worker may transition status queued->running->(succeeded|partial|failed|cancelled) only following the declared transitions.
- num_results_returned must equal the count of search_results rows for that search_request_id at the time the request is marked succeeded/partial.
- search_results must enforce unique(search_request_id, rank) and unique(search_request_id, publication_id) to prevent duplicates within a single request.
- Publications are deduplicated preferentially by scholar_cluster_id; if scholar_cluster_id is present and matches an existing active record, reuse that publication_id instead of inserting a new publication.
- publications.cited_by_count, author_profiles.cited_by_total, h_index, and i10_index must never be negative; ingestion must clamp or reject invalid scraped values.
- get_author_info(author_name) must resolve to author_profiles by normalized_name exact match; if none exists, create a new author_profiles row with status in ('active','not_found','blocked') based on fetch outcome.
- If an author profile fetch is blocked (e.g., captcha), set author_profiles.status='blocked' and do not overwrite last_fetched_at with a successful timestamp.
- When api_keys.daily_window_start_at is before the current UTC day, reset daily_requests_used to 0 and advance daily_window_start_at to the start of the current UTC day before counting the new request.
- Every accepted tool call increments api_keys.daily_requests_used by 1 atomically; if the increment would exceed daily_request_limit, reject with a quota error and do not create a search_requests row / do not refresh author_profiles.
- Deleting a search request (administrative) must cascade delete its search_results; publications and author_* records are not deleted because they are shared/deduplicated.