# arXiv Research Assistant — local MCP environment

This backend supports an arXiv-focused research assistant that crawls recent-category listing pages, runs keyword searches, fetches canonical paper metadata by arXiv id, and computes trend analytics over recent time windows. It stores normalized paper metadata, tracks scrape/search/query runs as first-class jobs with statuses, and keeps per-paper/category observations so trend analysis can be computed reproducibly from captured snapshots.

Repository: https://github.com/daheepk/arxiv-paper-mcp
Homepage: https://smithery.ai/server/@daheepk/arxiv-paper-mcp

## Datastore

- `papers.json` — Canonical arXiv paper records keyed by arXiv identifier, including metadata returned by search and paper-info fetches. (18 rows; fields: ['id', 'arxiv_id', 'version', 'title', 'abstract', 'authors', 'primary_category', 'all_categories', 'pdf_url', 'abs_url', 'published_at', 'updated_at_arxiv', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(arxiv_id)
  - constraint: version is null or version >= 1
  - constraint: status in ('active','tombstoned')
  - constraint: title <> ''
- `paper_categories.json` — Join table mapping papers to categories, enabling category-based scraping snapshots and trend calculations. (18 rows; fields: ['id', 'paper_id', 'category', 'is_primary', 'created_at', 'updated_at'])
  - constraint: foreign key (paper_id) references papers(id) on delete cascade
  - constraint: unique(paper_id, category)
  - constraint: category <> ''
- `crawl_runs.json` — Execution records for scraping the 'recent' page of a category and storing observed paper ordering and timestamps. (18 rows; fields: ['id', 'category', 'max_results', 'source_url', 'started_at', 'finished_at', 'http_status', 'error_message', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: max_results between 1 and 200
  - constraint: http_status is null or (http_status between 100 and 599)
  - constraint: category <> ''
  - constraint: source_url <> ''
- `crawl_run_items.json` — Observed items from a crawl_run, linking the run to the papers found and preserving ordering on the 'recent' page at that time. (18 rows; fields: ['id', 'crawl_run_id', 'paper_id', 'rank', 'observed_at', 'raw_snippet', 'created_at', 'updated_at'])
  - constraint: foreign key (crawl_run_id) references crawl_runs(id) on delete cascade
  - constraint: foreign key (paper_id) references papers(id) on delete restrict
  - constraint: unique(crawl_run_id, rank)
  - constraint: unique(crawl_run_id, paper_id)
- `search_queries.json` — Execution records for keyword-based arXiv searches and their result sets, used by search_papers and to support trend analysis inputs. (18 rows; fields: ['id', 'keyword', 'max_results', 'executed_at', 'status', 'error_message', 'result_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: keyword <> ''
  - constraint: max_results between 1 and 200
  - constraint: result_count is null or (result_count between 0 and max_results)
- `search_query_results.json` — Join table storing which papers were returned for a given search query, preserving rank and allowing deduplication across queries. (18 rows; fields: ['id', 'search_query_id', 'paper_id', 'rank', 'matched_fields', 'created_at', 'updated_at'])
  - constraint: foreign key (search_query_id) references search_queries(id) on delete cascade
  - constraint: foreign key (paper_id) references papers(id) on delete restrict
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, paper_id)

## Business rules enforced by the tools

- scrape_recent_category_papers(category, max_results) MUST create a crawl_runs row with (category, max_results, source_url) and transition status queued -> running -> (succeeded|failed).
- On a successful crawl_runs, the system MUST insert up to max_results crawl_run_items with contiguous ranks starting at 1 and observed_at within the crawl window (started_at..finished_at).
- search_papers(keyword, max_results) MUST create a search_queries row and transition status queued -> running -> (succeeded|failed); on success, result_count MUST equal the number of stored search_query_results and be <= max_results.
- get_paper_info(paper_id) MUST resolve paper_id to papers.arxiv_id; if no papers row exists, the system MUST create one (status=active) and backfill metadata, then update updated_at.
- papers.arxiv_id MUST be globally unique; any ingestion path encountering an existing arxiv_id MUST upsert rather than insert duplicates.
- paper_categories MUST reflect papers.primary_category when known: if is_primary=true for a (paper_id, category) row, then no other row for that paper_id may have is_primary=true.
- analyze_trends(category, days) MUST compute metrics using crawl_run_items joined to crawl_runs filtered by category and crawl_runs.created_at >= now() - interval days; days MUST be between 1 and 365.
- All FK relationships MUST enforce referential integrity; deleting a crawl_run or search_query MUST cascade-delete its item/result rows; papers MUST NOT be deleted while referenced (restrict).
- max_results for both scrape and search MUST be clamped or rejected outside [1,200] to prevent abusive load.