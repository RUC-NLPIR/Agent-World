# Semantic Scholar Server — local MCP environment

This backend supports a Semantic Scholar MCP server by storing executed search queries and caching fetched entities (papers, authors) plus paper-to-paper edges (citations/references). Main workflows are: run a search (store query + results), fetch paper/author details (cache and refresh), and fetch citations/references (store and update graph edges for a paper).

Repository: https://github.com/JackKuo666/semanticscholar-MCP-Server
Homepage: https://smithery.ai/server/@JackKuo666/semanticscholar-mcp-server

## Datastore

- `search_queries.json` — Logged Semantic Scholar search requests and their execution metadata; used to serve and audit search_semantic_scholar calls and to attach result rows. (18 rows; fields: ['id', 'query_text', 'num_results_requested', 'num_results_returned', 'status', 'error_message', 'vendor_request_id', 'vendor_latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: num_results_requested BETWEEN 1 AND 100
  - constraint: num_results_returned IS NULL OR num_results_returned BETWEEN 0 AND num_results_requested
  - constraint: query_text <> ''
  - constraint: INDEX(query_text)
- `search_results.json` — Materialized search results for a given search_queries row, preserving ranking and allowing later introspection without re-querying upstream. (17 rows; fields: ['id', 'search_query_id', 'rank', 'paper_id', 'score', 'snippet', 'created_at', 'updated_at'])
  - constraint: FOREIGN KEY(search_query_id) REFERENCES search_queries(id) ON DELETE CASCADE
  - constraint: FOREIGN KEY(paper_id) REFERENCES papers(id) ON DELETE RESTRICT
  - constraint: rank >= 1
  - constraint: unique(search_query_id, rank)
- `papers.json` — Cached Semantic Scholar paper records used by get_semantic_scholar_paper_details and as nodes for citations/references graphs. (18 rows; fields: ['id', 'title', 'abstract', 'year', 'venue', 'doi', 'url', 'fields_of_study', 'citation_count', 'reference_count', 'external_ids', 'status', 'last_fetched_at', 'fetched_etag', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(doi) WHERE doi IS NOT NULL
  - constraint: year IS NULL OR (year BETWEEN 1800 AND 2100)
  - constraint: citation_count IS NULL OR citation_count >= 0
  - constraint: reference_count IS NULL OR reference_count >= 0
- `authors.json` — Cached Semantic Scholar author profiles used by get_semantic_scholar_author_details and for attaching authorship to papers when present. (18 rows; fields: ['id', 'name', 'affiliations', 'homepage', 'paper_count', 'citation_count', 'h_index', 'external_ids', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: paper_count IS NULL OR paper_count >= 0
  - constraint: citation_count IS NULL OR citation_count >= 0
  - constraint: h_index IS NULL OR h_index >= 0
  - constraint: INDEX(last_fetched_at)
- `paper_edges.json` — Directed edges between papers representing citations and references; used to serve get_semantic_scholar_citations_and_references. (19 rows; fields: ['id', 'source_paper_id', 'target_paper_id', 'edge_type', 'context', 'is_influential', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: FOREIGN KEY(source_paper_id) REFERENCES papers(id) ON DELETE CASCADE
  - constraint: FOREIGN KEY(target_paper_id) REFERENCES papers(id) ON DELETE RESTRICT
  - constraint: source_paper_id <> target_paper_id
  - constraint: unique(source_paper_id, target_paper_id, edge_type)

## Business rules enforced by the tools

- Tool search_semantic_scholar(query, num_results) must create a search_queries row with query_text=query and num_results_requested=num_results (default 10) and status transitions queued->running->(succeeded|failed).
- search_semantic_scholar must upsert papers for returned items (papers.status=active) before inserting search_results rows referencing them.
- search_results must contain ranks 1..num_results_returned with no gaps, and must not exceed num_results_requested.
- Tool get_semantic_scholar_paper_details(paper_id) must return a papers row; if not present or stale (last_fetched_at older than configured TTL), it must fetch upstream, upsert papers, and set last_fetched_at.
- Tool get_semantic_scholar_author_details(author_id) must return an authors row; if not present or stale, it must fetch upstream, upsert authors, and set last_fetched_at.
- Tool get_semantic_scholar_citations_and_references(paper_id) must ensure papers(paper_id) exists (creating a minimal stub if necessary) and then refresh paper_edges for that source_paper_id, upserting edges with last_fetched_at set and marking edges not returned in the latest refresh as status=removed.
- All FK references must be valid at write time; deleting a search_queries row must cascade delete its search_results; deleting a papers row is disallowed if referenced as target_paper_id by any paper_edges row (RESTRICT).
- Numeric fields must obey non-negativity constraints (counts >= 0) and year bounds; invalid upstream data must be normalized to NULL rather than violating constraints.