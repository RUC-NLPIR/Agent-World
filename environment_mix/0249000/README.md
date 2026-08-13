# Paper Search — local MCP environment

Paper Search is an academic literature metasearch backend that issues queries to multiple providers (arXiv, PubMed, bioRxiv, medRxiv, Google Scholar), stores normalized paper metadata, and records per-query result sets. It also manages download/read workflows for PDFs (where supported), including caching downloaded files and extracted text content, with explicit lifecycle statuses for each job.

Repository: https://github.com/openags/paper-search-mcp
Homepage: https://smithery.ai/server/@openags/paper-search-mcp

## Datastore

- `search_queries.json` — Stores each search request against a specific provider and captures request parameters, execution status, and basic performance/diagnostics for the search tools. (18 rows; fields: ['id', 'provider', 'query', 'max_results', 'executed_at', 'completed_at', 'upstream_latency_ms', 'upstream_request_id', 'error_code', 'error_message', 'result_count', 'raw_response', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: max_results BETWEEN 1 AND 200
  - constraint: provider IN ('arxiv','pubmed','biorxiv','medrxiv','google_scholar')
  - constraint: result_count IS NULL OR result_count >= 0
  - constraint: completed_at IS NULL OR executed_at IS NOT NULL
- `papers.json` — Canonical normalized paper metadata across all providers. A single logical paper may appear in multiple providers; uniqueness is enforced per provider + provider_paper_id, with optional DOI deduplication. (18 rows; fields: ['id', 'provider', 'provider_paper_id', 'doi', 'title', 'abstract', 'authors', 'published_at', 'journal', 'source_url', 'pdf_url', 'raw_metadata', 'created_at', 'updated_at'])
  - constraint: unique(provider, provider_paper_id)
  - constraint: doi IS NULL OR length(doi) BETWEEN 3 AND 255
  - constraint: title <> ''
  - constraint: provider IN ('arxiv','pubmed','biorxiv','medrxiv','google_scholar')
- `search_results.json` — Join table connecting a search query to its resulting papers, preserving rank/order and any per-result provider fields (snippets, scores). (18 rows; fields: ['id', 'search_query_id', 'paper_id', 'rank', 'score', 'snippet', 'provider_payload', 'created_at', 'updated_at'])
  - constraint: rank >= 1
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, paper_id)
  - constraint: FK(search_query_id) REFERENCES search_queries(id) ON DELETE CASCADE
- `paper_assets.json` — Tracks downloadable and derived assets for a paper, including cached PDFs and extracted text. Supports download_* and read_* tools (for supported providers). (17 rows; fields: ['id', 'paper_id', 'asset_type', 'requested_save_path', 'storage_uri', 'content_sha256', 'byte_size', 'mime_type', 'text_content', 'status', 'failure_reason', 'last_attempted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['not_supported', 'queued', 'downloading', 'downloaded', 'extracting', 'ready', 'failed']
  - constraint: asset_type IN ('pdf','extracted_text')
  - constraint: unique(paper_id, asset_type)
  - constraint: byte_size IS NULL OR byte_size >= 0
  - constraint: content_sha256 IS NULL OR length(content_sha256) = 64

## Business rules enforced by the tools

- For each search tool call (search_arxiv/search_pubmed/search_biorxiv/search_medrxiv/search_google_scholar), the system MUST create a search_queries row with provider set accordingly, query set to the input query, and max_results set to the input max_results or default 10.
- max_results MUST default to 10 when omitted and MUST be clamped/rejected if outside [1, 200].
- When a search query status transitions to succeeded, result_count MUST equal the number of associated search_results rows for that search_query_id.
- A (provider, provider_paper_id) pair MUST uniquely identify a papers row; repeated searches returning the same paper MUST upsert/update the existing papers row rather than creating duplicates.
- Search results MUST preserve provider ordering; ranks MUST be contiguous starting at 1 up to result_count, and (search_query_id, rank) MUST be unique.
- For download_arxiv, download_biorxiv, and download_medrxiv: the system MUST ensure a papers row exists for the given provider and paper_id, then create/update a paper_assets row with asset_type='pdf' and requested_save_path set to save_path (default './downloads').
- For download_pubmed: the system MUST create/update a paper_assets row with asset_type='pdf' and status='not_supported' with failure_reason indicating direct PDF download is unsupported.
- For read_arxiv_paper, read_biorxiv_paper, read_medrxiv_paper: the system MUST ensure a PDF asset exists and is downloaded (or download it), then create/update a paper_assets row with asset_type='extracted_text' and status progressing to ready with text_content populated.
- For read_pubmed_paper: the system MUST return a not supported message and MUST mark any corresponding extracted_text asset as status='not_supported'.
- paper_assets.status MUST follow the declared transitions; in particular, ready MUST be terminal, and failed MAY only transition back to queued for retry.
- requested_save_path MUST be stored exactly as provided by the tool call (including default './downloads') for traceability, even if the backend uses a different storage_uri internally.
- Deleting a papers row MUST cascade-delete its paper_assets and search_results rows to avoid orphaned assets/results.