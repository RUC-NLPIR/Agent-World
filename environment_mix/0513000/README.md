# Google Scholar MCP Server — local MCP environment

This backend stores Google Scholar search activity and retrieved entities (papers/publications and authors) for an MCP server that can run keyword and advanced searches and fetch author profiles. Core workflows are: create a search request, execute it (scrape/fetch), persist normalized results (papers/authors) plus a per-request result snapshot, and serve reads from stored entities and prior runs.

Repository: https://github.com/JackKuo666/Google-Scholar-MCP-Server
Homepage: https://smithery.ai/server/@JackKuo666/google-scholar-mcp-server

## Datastore

- `api_keys.json` — API credentials used to authenticate and quota-limit callers of the MCP server (even if the public tool surface does not expose key management). (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'rate_limit_per_minute', 'daily_request_quota', 'daily_requests_used', 'quota_reset_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: rate_limit_per_minute between 1 and 600
  - constraint: daily_request_quota between 0 and 1000000
- `search_requests.json` — A single invocation of a Scholar search tool (keyword or advanced). Stores the raw user intent and the execution state, enabling replay, caching, and audit. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'raw_parameters', 'query_text', 'advanced_criteria', 'locale', 'num_results_requested', 'status', 'error_code', 'error_message', 'started_at', 'finished_at', 'result_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: num_results_requested between 1 and 200
  - constraint: result_count >= 0
  - constraint: tool_name in ('search_google_scholar_key_words','search_google_scholar_advanced')
  - constraint: finished_at is null when status in ('queued','running')
- `papers.json` — Normalized publication records returned by Scholar searches. Deduplicated by canonical identifiers when available. (18 rows; fields: ['id', 'scholar_cluster_id', 'title', 'publication_venue', 'publication_year', 'snippet', 'citation_count', 'pdf_url', 'landing_url', 'created_at', 'updated_at'])
  - constraint: unique(scholar_cluster_id) where scholar_cluster_id is not null
  - constraint: citation_count >= 0
  - constraint: publication_year between 1600 and 2200 or publication_year is null
- `authors.json` — Author profiles retrievable via get_author_info and also discoverable from paper metadata when available. (18 rows; fields: ['id', 'scholar_author_id', 'name', 'affiliation', 'email_domain', 'interests', 'homepage_url', 'cited_by', 'h_index', 'i10_index', 'profile_last_fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'disabled']
  - constraint: unique(scholar_author_id)
  - constraint: cited_by >= 0
  - constraint: h_index >= 0
  - constraint: i10_index >= 0
- `search_results.json` — Per-search snapshot of results in rank order, linking search requests to the normalized paper and optionally extracted author entities. (18 rows; fields: ['id', 'search_request_id', 'rank', 'paper_id', 'result_source_url', 'raw_result', 'created_at', 'updated_at'])
  - constraint: unique(search_request_id, rank)
  - constraint: unique(search_request_id, paper_id)
  - constraint: rank between 1 and 200
  - constraint: fk(search_request_id) references search_requests(id) on delete cascade

## Business rules enforced by the tools

- Calling search_google_scholar_key_words must create a search_requests row with tool_name='search_google_scholar_key_words', raw_parameters='{}' (or provided JSON), status transitions queued->running->(succeeded|failed|cancelled), and then insert 0..num_results_requested search_results rows on success.
- Calling search_google_scholar_advanced must create a search_requests row with tool_name='search_google_scholar_advanced'; if advanced criteria can be inferred, store it in advanced_criteria; execution and persistence rules match the keyword tool.
- Calling get_author_info must upsert an authors row by scholar_author_id, update profile fields, set profile_last_fetched_at=now(), and set status='active' unless the profile is unreachable/blocked, in which case status may become 'stale' and the operation must record the failure in server logs (not modeled) without corrupting existing author data.
- If an api_key_id is present on a request, the system must enforce: api_keys.status='active', daily_requests_used < daily_request_quota, and a per-minute rate limit <= rate_limit_per_minute; otherwise the request must be rejected and no search_requests row should be persisted (or it must be persisted with status='failed' and error_code='UNAUTHORIZED' depending on deployment policy).
- papers must be deduplicated by scholar_cluster_id when available; inserting a paper with an existing scholar_cluster_id must update the existing row (title/venue/year/snippet/urls/citation_count) rather than create a duplicate.
- When a search_requests row reaches status='succeeded', result_count must equal count(search_results where search_request_id=id), and finished_at must be non-null and >= started_at.
- Deleting a search_requests row must cascade-delete its search_results rows to prevent orphaned snapshots; papers and authors are not deleted by this operation.