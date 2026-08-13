# Semantic Scholar Academic Research MCP — local MCP environment

This backend powers an MCP wrapper around the Semantic Scholar Graph API by persisting cached entities (papers/authors), relationships (authorship and citations), and the operational history of searches/recommendation/snippet queries. The main workflow is: accept a tool call, log the request, fetch/refresh upstream data as needed, store normalized entities and edges, then store and return the result set for reproducibility, rate limiting, and debugging.

Repository: https://github.com/alperenkocyigit/semantic-scholar-graph-api
Homepage: https://smithery.ai/server/@alperenkocyigit/semantic-scholar-graph-api

## Datastore

- `api_clients.json` — Represents callers of this MCP service (e.g., an MCP client instance/workspace) for quota/rate-limiting and auditing of tool usage. (20 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'daily_request_limit', 'daily_request_count', 'daily_reset_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: daily_request_limit >= 0
  - constraint: daily_request_count >= 0
- `papers.json` — Normalized cache of Semantic Scholar papers and their core metadata; used to serve paper details, batch fetches, recommendations, snippets, and citation/reference edges. (39 rows; fields: ['id', 'semantic_scholar_paper_id', 'title', 'abstract', 'year', 'venue', 'doi', 'url', 'citation_count', 'reference_count', 'influential_citation_count', 'status', 'fetched_at', 'source_etag', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(semantic_scholar_paper_id)
  - constraint: year is null OR (year >= 1800 AND year <= 2100)
  - constraint: citation_count is null OR citation_count >= 0
  - constraint: reference_count is null OR reference_count >= 0
- `authors.json` — Normalized cache of Semantic Scholar authors and their core metadata; used to serve author details and author batch fetches, and to join papers via authorship. (31 rows; fields: ['id', 'semantic_scholar_author_id', 'name', 'affiliations', 'homepage', 'paper_count', 'citation_count', 'h_index', 'status', 'fetched_at', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(semantic_scholar_author_id)
  - constraint: paper_count is null OR paper_count >= 0
  - constraint: citation_count is null OR citation_count >= 0
  - constraint: h_index is null OR h_index >= 0
- `paper_edges.json` — Stores graph relationships around papers: authorship (paper<->author) and citations/references (paper<->paper). Supports citations_and_references queries and efficient graph traversals for recommendations. (31 rows; fields: ['id', 'edge_type', 'from_paper_id', 'to_paper_id', 'author_id', 'author_position', 'is_influential', 'status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: CHECK( (edge_type = 'CITES' AND from_paper_id IS NOT NULL AND to_paper_id IS NOT NULL AND author_id IS NULL) OR (edge_type = 'AUTHORED_BY' AND from_paper_id IS NOT NULL AND author_id IS NOT NULL AND to_paper_id IS NULL) )
  - constraint: unique(edge_type, from_paper_id, to_paper_id, author_id)
  - constraint: author_position is null OR author_position >= 0
  - constraint: CHECK(edge_type != 'CITES' OR from_paper_id != to_paper_id)
- `tool_requests.json` — Immutable log of every tool invocation and its materialized result set pointers. Enables debugging, caching, replay, and enforcing per-client limits. All 12 tools map to rows here. (37 rows; fields: ['id', 'client_id', 'tool_name', 'status', 'query', 'num_results', 'limit', 'paper_id', 'author_id', 'paper_ids', 'author_ids', 'positive_paper_ids', 'negative_paper_ids', 'upstream_http_status', 'upstream_latency_ms', 'error_message', 'result_summary', 'result_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: num_results is null OR (num_results >= 1 AND num_results <= 1000)
  - constraint: limit is null OR (limit >= 1 AND limit <= 1000)
  - constraint: CHECK(tool_name != 'search_semantic_scholar' OR num_results IS NOT NULL)
  - constraint: CHECK(tool_name NOT IN ('search_semantic_scholar_authors','search_semantic_scholar_snippets','get_semantic_scholar_paper_recommendations','get_semantic_scholar_paper_recommendations_from_lists') OR limit IS NOT NULL)

## Business rules enforced by the tools

- A tool call must create exactly one tool_requests row with status=received, then transition to running and finally to succeeded or failed; no other transitions are allowed.
- Requests must be rejected when api_clients.status in ('suspended','revoked').
- Before executing a tool, the service must enforce api_clients.daily_request_count + 1 <= api_clients.daily_request_limit; upon acceptance it increments daily_request_count atomically.
- search_semantic_scholar requires query (non-empty after trimming) and num_results in [1,1000]; results are served from cached papers when sufficiently fresh, otherwise upstream is queried and papers upserted.
- get_semantic_scholar_paper_details requires paper_id; if papers.semantic_scholar_paper_id is unknown or stale, fetch upstream and upsert into papers; return normalized fields plus raw_payload when present.
- get_semantic_scholar_author_details requires author_id; if authors.semantic_scholar_author_id is unknown or stale, fetch upstream and upsert into authors.
- get_semantic_scholar_citations_and_references requires paper_id; the service must ensure the subject paper exists in papers (upsert if needed), then refresh/insert CITES edges for both citations and references, marking removed edges as deleted.
- search_semantic_scholar_authors requires query (non-empty) and limit in [1,100]; enforce the tighter max=100 at runtime even if tool schema allows higher.
- get_semantic_scholar_paper_autocomplete requires query truncated to 100 characters; store the truncated query in tool_requests.query.
- Batch tools must enforce hard limits: paper_ids length <= 500; author_ids length <= 1000; reject otherwise.
- search_semantic_scholar_snippets requires query (non-empty) and limit in [1,1000]; snippet result payloads may be stored in tool_requests.result_payload but must not be persisted into papers unless a paper is separately fetched/upserted.
- Recommendation tools must enforce limit in [1,500] for both get_semantic_scholar_paper_recommendations and get_semantic_scholar_paper_recommendations_from_lists (even if not fully visible in truncated description), and must upsert any returned recommended papers into papers.
- When upserting papers/authors, semantic_scholar_*_id is immutable; updates must only modify metadata fields, raw_payload, fetched_at, and updated_at.
- paper_edges must satisfy structural integrity: CITES edges require from_paper_id and to_paper_id; AUTHORED_BY edges require from_paper_id and author_id; mixed/partial combinations are invalid.
- For authorship refresh, the service should maintain a contiguous author_position ordering starting at 0 for a given paper where upstream provides ordering; duplicates for the same paper and author are forbidden by unique constraint.