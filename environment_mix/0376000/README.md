# Movie Recommender — local MCP environment

This backend stores a curated catalog of movies enriched with searchable keywords and tracks user/API access for the single search endpoint. The primary workflow is: accept a keyword, normalize it, log the search request, and return matching movies ranked by simple relevance while enforcing basic API key validity and rate limits.

Repository: https://github.com/iremert/movie-recommender-mcp
Homepage: https://smithery.ai/server/@iremert/movie-recommender-mcp

## Datastore

- `api_keys.json` — API keys used to authenticate and rate-limit access to the Movie Recommender search endpoint. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'rate_limit_per_minute', 'daily_quota_requests', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute between 1 and 6000
  - constraint: daily_quota_requests between 1 and 1000000
- `movies.json` — Movie catalog entries returned as suggestions from keyword search. (18 rows; fields: ['id', 'title', 'original_title', 'overview', 'release_year', 'language', 'popularity', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'deleted']
  - constraint: unique(title, release_year)
  - constraint: release_year between 1878 and 2100 (nullable)
  - constraint: popularity >= 0
- `movie_keywords.json` — Normalized keywords/tags for each movie to support keyword search and simple relevance scoring. (18 rows; fields: ['id', 'movie_id', 'keyword', 'keyword_normalized', 'weight', 'source', 'created_at', 'updated_at'])
  - constraint: foreign key(movie_id) references movies(id) on delete cascade
  - constraint: unique(movie_id, keyword_normalized, source)
  - constraint: length(keyword_normalized) between 1 and 128
  - constraint: weight between 0 and 100
- `search_requests.json` — Audit log of get_movies calls for debugging, analytics, and quota enforcement. (18 rows; fields: ['id', 'api_key_id', 'keyword_raw', 'keyword_normalized', 'status', 'result_count', 'latency_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'fulfilled', 'rejected', 'error']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: length(keyword_raw) between 1 and 256
  - constraint: length(keyword_normalized) between 1 and 256
  - constraint: result_count >= 0 (nullable)
- `search_results.json` — Per-request ranked results for get_movies, enabling reproducibility and lightweight analytics. (17 rows; fields: ['id', 'search_request_id', 'movie_id', 'rank', 'score', 'matched_tokens', 'created_at', 'updated_at'])
  - constraint: foreign key(search_request_id) references search_requests(id) on delete cascade
  - constraint: foreign key(movie_id) references movies(id) on delete restrict
  - constraint: unique(search_request_id, rank)
  - constraint: unique(search_request_id, movie_id)

## Business rules enforced by the tools

- get_movies(keyword) must normalize keyword into keyword_normalized by trimming, lowercasing, and collapsing internal whitespace; the stored keyword_raw must equal the incoming parameter.
- For each get_movies call, a search_requests row must be created with status='received' before query execution; it must transition to exactly one terminal state: fulfilled, rejected, or error.
- A request must be rejected (status='rejected') when keyword_raw is empty/blank after trimming, or exceeds 256 characters after normalization.
- If an API key is required by deployment configuration, calls without a valid api_keys record in status='active' must be rejected and logged; when accepted, api_keys.last_used_at must be updated.
- Rate limiting must be enforced per api_key_id: no more than rate_limit_per_minute successful or rejected requests per rolling minute; exceeding the limit yields status='rejected' with an error_code like 'rate_limited'.
- Daily quota must be enforced per api_key_id based on search_requests.created_at (UTC day): if count exceeds daily_quota_requests, the request must be rejected with error_code 'quota_exceeded'.
- Movie matching for get_movies must only consider movies.status='active' and movie_keywords.keyword_normalized matches (exact or prefix/contains depending on implementation); inactive/deleted movies must never appear in search_results.
- When status='fulfilled', search_requests.result_count must equal the number of search_results rows for that search_request_id; ranks must be contiguous starting at 1.
- search_results may only be inserted for search_requests in status='received' during processing; once the request is terminal, results are immutable (updates only allowed for backfill jobs that also update updated_at and record an operational audit externally).
- Deleting a movie must be implemented as a status transition to 'deleted' (soft delete); hard deletes are disallowed while referenced by search_results.