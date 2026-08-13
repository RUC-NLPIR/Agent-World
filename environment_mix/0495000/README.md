# AI Research Assistant - Semantic Scholar — local MCP environment

This backend stores a locally cached mirror of Semantic Scholar entities (papers, authors) plus their graph relationships (authorship and citations). It supports full-text/semantic search, filtered retrieval, pagination, batch lookups, and higher-level citation-network analysis derived from the stored citation graph.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@hamid-vakilzadeh/mcpsemanticscholar

## Datastore

- `papers.json` — Canonical paper records normalized from Semantic Scholar and other identifier schemes (S2, DOI, arXiv). Used by paper lookup, search result hydration, and graph analysis. (18 rows; fields: ['id', 'source', 's2_paper_id', 'doi', 'arxiv_id', 'pubmed_id', 'title', 'title_normalized', 'abstract', 'year', 'venue', 'publication_types', 'fields_of_study', 'is_open_access', 'open_access_pdf_url', 'citation_count', 'reference_count', 'embedding', 'status', 'merged_into_paper_id', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned', 'merged']
  - constraint: citation_count >= 0
  - constraint: reference_count >= 0
  - constraint: year IS NULL OR (year >= 1600 AND year <= 2100)
  - constraint: unique(s2_paper_id) WHERE s2_paper_id IS NOT NULL
- `authors.json` — Author entities (Semantic Scholar author id) used for author search and listing papers by author. (18 rows; fields: ['id', 's2_author_id', 'name', 'name_normalized', 'affiliations', 'paper_count', 'citation_count', 'h_index', 'status', 'merged_into_author_id', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned', 'merged']
  - constraint: unique(s2_author_id)
  - constraint: paper_count >= 0
  - constraint: citation_count >= 0
  - constraint: h_index IS NULL OR h_index >= 0
- `paper_authors.json` — Many-to-many join between papers and authors with ordering and author metadata as displayed on the paper. (18 rows; fields: ['id', 'paper_id', 'author_id', 'author_order', 'author_name_on_paper', 'created_at', 'updated_at'])
  - constraint: foreign key(paper_id) references papers(id) on delete cascade
  - constraint: foreign key(author_id) references authors(id) on delete cascade
  - constraint: author_order >= 1
  - constraint: unique(paper_id, author_id)
- `paper_citations.json` — Directed citation edges between papers. A row means citing_paper cites cited_paper. Used for citations/references endpoints and citation-network analysis. (18 rows; fields: ['id', 'citing_paper_id', 'cited_paper_id', 'context', 'is_influential', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign key(citing_paper_id) references papers(id) on delete cascade
  - constraint: foreign key(cited_paper_id) references papers(id) on delete cascade
  - constraint: citing_paper_id != cited_paper_id
  - constraint: unique(citing_paper_id, cited_paper_id)
- `search_requests.json` — Audit and caching layer for search/match/analysis requests. Stores request parameters, derived filters, and a materialized list of matched paper ids for fast pagination. (19 rows; fields: ['id', 'tool_name', 'query', 'title', 'paper_id_input', 'author_id_input', 'paper_ids_input', 'year_start', 'year_end', 'min_citations', 'open_access_only', 'fields_of_study', 'publication_types', 'sort_by', 'sort_order', 'limit', 'offset', 'depth', 'citations_limit', 'references_limit', 'resolved_root_paper_id', 'resolved_author_id', 'result_paper_ids', 'result_author_ids', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: limit IS NULL OR (limit >= 1 AND limit <= 100)
  - constraint: offset IS NULL OR offset >= 0
  - constraint: min_citations IS NULL OR min_citations >= 0
  - constraint: year_start IS NULL OR (year_start >= 1600 AND year_start <= 2100)

## Business rules enforced by the tools

- papers-get must resolve paperId by trying, in order: internal papers.id, papers.s2_paper_id, papers.doi (normalized), papers.arxiv_id, papers.pubmed_id; if a paper is status=merged it must return the merged_into_paper_id record.
- papers-batch must preserve input order in the output; any unknown ids must be omitted (or returned as not_found) but must not be silently mapped to an unrelated paper.
- papers-search-basic must create a search_requests row with tool_name='papers-search-basic' and store query and limit; execution must populate result_paper_ids ordered by relevance.
- papers-search-advanced must apply filters over papers: year between yearStart/yearEnd (inclusive), citation_count >= minCitations, is_open_access=true when openAccessOnly, intersection match for fields_of_study and publication_types; sorting must honor (sortBy, sortOrder) where sortBy='relevance' uses text/embedding rank, 'citationCount' uses citation_count, and 'year' uses year.
- papers-match must use title_normalized similarity (e.g., trigram/cosine over embeddings) constrained by the same optional filters (yearStart/yearEnd/minCitations/openAccessOnly) and return the top ranked paper; ties break by higher citation_count then newer year.
- papers-citations must return papers that cite the target paper: join paper_citations where cited_paper_id = resolved target and status='active'; pagination uses (offset, limit) over a stable order (default: newest year desc then citation_count desc then id).
- papers-references must return papers cited by the target paper: join paper_citations where citing_paper_id = resolved target and status='active'; pagination uses (offset, limit) with the same stable ordering policy.
- authors-search must search over authors.name_normalized and affiliations (substring/full-text) and return result_author_ids with pagination via offset/limit.
- authors-papers must return papers for a resolved author via paper_authors; pagination uses (offset, limit) over a stable order (default: year desc then citation_count desc then id).
- analysis-citation-network must accept depth as string input but validate it parses to integer 1 or 2; it must compute a subgraph starting from resolved_root_paper_id including up to citationsLimit inbound edges per visited node and up to referencesLimit outbound edges per visited node, using paper_citations.status='active'.
- All endpoints must enforce limit defaults of 10 and clamp maximum limit to 100; offset must be >= 0.
- FK integrity: paper_authors.paper_id and paper_citations.* must reference existing papers; paper_authors.author_id must reference existing authors; deletes of a paper/author must cascade to join/edge rows.