# arXiv Server — local MCP environment

This backend powers an arXiv query service that executes searches against the arXiv API, caches paper metadata, and records query executions for observability and throttling. The main workflows are: (1) accept a search request, persist a query job, fetch/parse arXiv results, upsert papers/authors/categories, and store a result set; (2) retrieve paper details by arXiv ID(s) from cache with optional refresh when stale.

Repository: https://github.com/candenizkocak/arxiv-mcp-server
Homepage: https://smithery.ai/server/@candenizkocak/arxiv-mcp-server

## Datastore

- `api_clients.json` — Represents a calling client (API key / integration) and its quota policy used to rate-limit and audit tool usage. (18 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'requests_per_minute', 'max_results_cap', 'last_request_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: requests_per_minute between 1 and 6000
  - constraint: max_results_cap between 1 and 200
- `papers.json` — Canonical cached representation of an arXiv paper and its primary metadata required by the tools. (17 rows; fields: ['id', 'arxiv_id', 'version', 'title', 'abstract', 'primary_category', 'categories', 'doi', 'journal_ref', 'comment', 'pdf_url', 'abs_url', 'submitted_at', 'last_updated_at', 'cache_status', 'source_fetched_at', 'source_etag', 'created_at', 'updated_at'])
  - lifecycle `cache_status`: ['fresh', 'stale', 'refreshing', 'error']
  - constraint: unique(arxiv_id)
  - constraint: title != ''
  - constraint: version is null or version >= 1
  - constraint: categories length >= 0
- `authors.json` — Normalized author identities as observed in arXiv metadata; supports author-based search indexing and joins. (18 rows; fields: ['id', 'canonical_name', 'name_normalized', 'status', 'merged_into_author_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'merged', 'deleted']
  - constraint: unique(name_normalized)
  - constraint: canonical_name != ''
  - constraint: merged_into_author_id is null or merged_into_author_id != id
- `paper_authors.json` — Join table between papers and authors preserving author ordering and the raw display name used in the arXiv feed. (18 rows; fields: ['id', 'paper_id', 'author_id', 'author_position', 'raw_author_name', 'created_at', 'updated_at'])
  - constraint: foreign key(paper_id) references papers(id) on delete cascade
  - constraint: foreign key(author_id) references authors(id) on delete restrict
  - constraint: unique(paper_id, author_position)
  - constraint: author_position >= 1
- `query_runs.json` — Audit log of tool invocations that execute arXiv searches and the resulting paper ids returned, including sorting and limiting inputs from the tool surface. (20 rows; fields: ['id', 'client_id', 'tool_name', 'query', 'author_name', 'category', 'requested_arxiv_id', 'requested_arxiv_ids', 'max_results', 'sort_by', 'sort_order', 'status', 'http_status', 'error_message', 'started_at', 'finished_at', 'result_count', 'result_paper_ids', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign key(client_id) references api_clients(id) on delete restrict
  - constraint: max_results is null or max_results between 1 and 200
  - constraint: result_count is null or result_count >= 0
  - constraint: http_status is null or http_status between 100 and 599

## Business rules enforced by the tools

- For every tool invocation, the service MUST create a query_runs row with tool_name and input parameters captured (query/author_name/category/arxiv_id(s), max_results, sort_by, sort_order) and transition status from queued->running->(succeeded|failed).
- search_papers MUST map query_runs.query to the provided arXiv syntax string; find_papers_by_author MUST derive query_runs.query as an author query (e.g., au:"{author_name}"); get_latest_from_category MUST derive query_runs.query as a category query (e.g., cat:{category}).
- max_results MUST be clamped to min(requested max_results, api_clients.max_results_cap) and MUST be >= 1.
- sort_by MUST be one of: relevance, lastUpdatedDate, submittedDate; sort_order MUST be one of: ascending, descending. If omitted, defaults are applied and stored on query_runs.
- get_paper_by_id and get_papers_by_ids MUST look up papers by papers.arxiv_id; if not found or cache_status in (stale,error), the service SHOULD fetch from arXiv, upsert papers, and set cache_status to fresh on success or error on failure.
- All fetched/parsed papers MUST be upserted into papers with unique(arxiv_id); authors MUST be upserted into authors with unique(name_normalized); paper_authors MUST be rewritten to match the latest author list and preserve author_position uniqueness per paper.
- get_latest_from_category MUST only return papers where the requested category matches either papers.primary_category or is contained in papers.categories (after refresh/caching as needed).
- query_runs.result_paper_ids MUST reference existing papers.id values at the time status becomes succeeded; result_count MUST equal the length of result_paper_ids.
- API client enforcement: if api_clients.status != 'active' the service MUST reject requests and MUST NOT execute an upstream fetch; optionally a failed query_runs row may be recorded with error_message.
- FK integrity MUST be enforced: deleting a paper MUST cascade delete its paper_authors rows; deleting an author referenced by paper_authors MUST be blocked.