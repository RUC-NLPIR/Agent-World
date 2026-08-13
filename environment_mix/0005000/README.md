# medRxiv MCP Server — local MCP environment

This backend supports a medRxiv search/metadata MCP service by storing executed search requests, their parameters, cached results, and normalized preprint metadata keyed by DOI. Primary workflows are: (1) execute keyword/advanced searches and return ranked preprints; (2) fetch and cache full metadata for a specific DOI; (3) reuse cached documents/results to reduce repeated upstream calls and enforce operational limits.

Repository: https://github.com/JackKuo666/medRxiv-MCP-Server
Homepage: https://smithery.ai/server/@JackKuo666/medrxiv-mcp-server

## Datastore

- `api_clients.json` — Represents an internal or external caller identity (per MCP server deployment) used for auditing, throttling, and caching policy. (12 rows; fields: ['id', 'name', 'status', 'api_key_hash', 'daily_request_limit', 'daily_requests_used', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: daily_request_limit >= 0
  - constraint: daily_requests_used >= 0
  - constraint: daily_requests_used <= daily_request_limit OR daily_request_limit = 0 (0 means unlimited)
- `preprints.json` — Normalized medRxiv preprint metadata keyed by DOI. This is the canonical document table returned by searches and DOI lookups. (42 rows; fields: ['id', 'doi', 'server', 'title', 'abstract', 'authors', 'author_corresponding', 'author_corresponding_institution', 'category', 'version', 'posted_date', 'published_journal', 'published_date', 'license', 'url', 'pdf_url', 'status', 'metadata_fetched_at', 'metadata_etag', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(doi)
  - constraint: doi LIKE '%/%' (basic DOI shape validation)
  - constraint: version IS NULL OR version >= 1
- `search_requests.json` — Stores each search invocation (keyword or advanced), its normalized parameters, execution status, and timing for auditing and caching. (32 rows; fields: ['id', 'client_id', 'tool_name', 'key_words', 'term', 'title', 'author1', 'author2', 'abstract_title', 'text_abstract_title', 'section', 'start_date', 'end_date', 'num_results', 'normalized_query_hash', 'status', 'upstream_cache_hit', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: num_results >= 1 AND num_results <= 200
  - constraint: tool_name = 'search_medrxiv_key_words' => key_words IS NOT NULL
  - constraint: tool_name = 'search_medrxiv_key_words' => term IS NULL AND title IS NULL AND author1 IS NULL AND author2 IS NULL AND abstract_title IS NULL AND text_abstract_title IS NULL AND section IS NULL AND start_date IS NULL AND end_date IS NULL
  - constraint: tool_name = 'search_medrxiv_advanced' => (term IS NOT NULL OR title IS NOT NULL OR author1 IS NOT NULL OR author2 IS NOT NULL OR abstract_title IS NOT NULL OR text_abstract_title IS NOT NULL OR section IS NOT NULL OR start_date IS NOT NULL OR end_date IS NOT NULL)
- `search_results.json` — Join table that stores the ranked results for a search request, referencing canonical preprints by DOI. (30 rows; fields: ['id', 'search_request_id', 'preprint_id', 'rank', 'score', 'snippet', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: rank >= 1
  - constraint: unique(search_request_id, rank)
  - constraint: unique(search_request_id, preprint_id)
  - constraint: FK(search_request_id) ON DELETE CASCADE
- `doi_metadata_requests.json` — Tracks invocations of get_medrxiv_metadata(doi), including cache behavior and linkage to the canonical preprint record. (32 rows; fields: ['id', 'client_id', 'doi', 'preprint_id', 'status', 'cache_hit', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'not_found', 'failed']
  - constraint: doi LIKE '%/%' (basic DOI shape validation)
  - constraint: status = 'succeeded' => preprint_id IS NOT NULL
  - constraint: unique(client_id, doi) WHERE status IN ('queued','running')

## Business rules enforced by the tools

- search_medrxiv_key_words must create a search_requests row with tool_name='search_medrxiv_key_words', key_words set, num_results set (default 10), and all advanced-only fields NULL.
- search_medrxiv_advanced must create a search_requests row with tool_name='search_medrxiv_advanced', num_results set (default 10), and at least one of term/title/author1/author2/abstract_title/text_abstract_title/section/start_date/end_date non-NULL.
- For search_medrxiv_advanced, if both start_date and end_date are provided then start_date must be <= end_date; invalid inputs fail the request with status='failed'.
- Each successful search request must populate 1..num_results rows in search_results with contiguous rank starting at 1; duplicates by preprint_id within the same search_request_id are not allowed.
- get_medrxiv_metadata must create a doi_metadata_requests row; on success it must upsert preprints by doi and set doi_metadata_requests.preprint_id to the upserted row.
- preprints.doi is globally unique; any tool that encounters the same DOI must reference the existing preprints row rather than creating a duplicate.
- Client throttling: for an api_clients row with daily_request_limit > 0, the service must not allow (daily_requests_used + 1) > daily_request_limit; rejected requests must not create search_requests/doi_metadata_requests rows (or must be recorded with status='failed' and an error_message indicating quota exceeded, consistently per implementation).
- Caching: a request is considered a cache hit if an identical normalized_query_hash (and num_results) previously succeeded within a configured TTL; cache hits must set search_requests.upstream_cache_hit=true and reuse existing preprints/search_results data.
- Metadata freshness: get_medrxiv_metadata may treat preprints.metadata_fetched_at within a configured TTL as cache_hit=true; otherwise it should refetch and update preprints.updated_at and metadata_fetched_at.
- Deletes are logical: api_clients with status='deleted' and preprints with status='tombstoned' must not be returned in new search results, but historical search_requests/search_results remain intact.