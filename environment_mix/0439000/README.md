# PubMed MCP Server — local MCP environment

This backend stores PubMed search requests, the resulting article hits, and a normalized cache of PubMed article metadata keyed by PMID. It also tracks PDF download attempts (often via PMC/Publisher links) and retains fetch outcomes, enabling rate limiting, auditing, and response caching for the MCP tools.

Repository: https://github.com/JackKuo666/PubMed-MCP-Server
Homepage: https://smithery.ai/server/@JackKuo666/pubmed-mcp-server

## Datastore

- `api_clients.json` — Represents a calling client (MCP user, app, or integration) and its quota/limits used for PubMed E-utilities traffic and PDF retrieval. (12 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'daily_search_limit', 'daily_metadata_limit', 'daily_pdf_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: daily_search_limit BETWEEN 0 AND 1000000
  - constraint: daily_metadata_limit BETWEEN 0 AND 1000000
- `search_requests.json` — Stores a search invocation (keyword or advanced) and the normalized parameters used to generate a PubMed query. (35 rows; fields: ['id', 'client_id', 'tool_name', 'key_words', 'term', 'title', 'author', 'journal', 'start_date', 'end_date', 'num_results', 'normalized_query', 'status', 'pubmed_retmax', 'pubmed_webenv', 'pubmed_query_key', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: num_results BETWEEN 1 AND 500
  - constraint: pubmed_retmax BETWEEN 1 AND 500
  - constraint: tool_name='search_pubmed_key_words' implies key_words IS NOT NULL AND (term IS NULL AND title IS NULL AND author IS NULL AND journal IS NULL AND start_date IS NULL AND end_date IS NULL)
- `search_results.json` — Stores PubMed IDs returned for a given search request with rank/order. This powers returning lists of PMIDs and allows caching and later metadata fetches. (31 rows; fields: ['id', 'search_request_id', 'pmid', 'rank', 'created_at', 'updated_at'])
  - constraint: fk(search_request_id) references search_requests(id) on delete cascade
  - constraint: unique(search_request_id, pmid)
  - constraint: unique(search_request_id, rank)
  - constraint: rank BETWEEN 1 AND 500
- `articles.json` — Canonical cache of PubMed article metadata keyed by PMID, used by get_pubmed_article_metadata and to enrich search results. (34 rows; fields: ['id', 'pmid', 'status', 'title', 'abstract', 'journal', 'publication_date', 'authors', 'doi', 'pmc_id', 'mesh_terms', 'keywords', 'source_url', 'raw_metadata', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'stale', 'fetch_failed', 'deleted']
  - constraint: unique(pmid)
  - constraint: pmid matches ^[0-9]+$
  - constraint: publication_date IS NULL OR publication_date matches YYYY-MM-DD
- `pdf_downloads.json` — Tracks attempts to locate and download a PDF for a PMID (often via PMC when available). Stores outcome and pointers to the retrieved file if any. (30 rows; fields: ['id', 'client_id', 'pmid', 'article_id', 'status', 'resolved_pdf_url', 'http_status', 'content_type', 'file_sha256', 'file_size_bytes', 'storage_uri', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'downloaded', 'not_found', 'forbidden', 'failed']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: fk(article_id) references articles(id) on delete set null
  - constraint: pmid matches ^[0-9]+$
  - constraint: http_status IS NULL OR http_status BETWEEN 100 AND 599

## Business rules enforced by the tools

- search_pubmed_key_words must create a search_requests row with tool_name='search_pubmed_key_words', key_words populated, and advanced fields NULL; it must set num_results to the provided value or default 10 and cap it to 500 when persisting pubmed_retmax.
- search_pubmed_advanced must create a search_requests row with tool_name='search_pubmed_advanced' and key_words NULL; it may accept NULL for any of term/title/author/journal/start_date/end_date; it must set num_results to the provided value or default 10 and cap it to 500 when persisting pubmed_retmax.
- Both search tools must transition search_requests.status from queued -> running -> (succeeded|failed) and persist any returned PMIDs into search_results with contiguous 1-based rank up to pubmed_retmax.
- get_pubmed_article_metadata(pmid) must return the cached articles row when status='available' and last_fetched_at is within the freshness window; otherwise it must fetch upstream and upsert articles by unique pmid, updating raw_metadata and last_fetched_at and setting status to 'available' on success or 'fetch_failed' on failure.
- download_pubmed_pdf(pmid) must create a pdf_downloads row and transition status queued -> fetching -> terminal; it must not mark downloaded unless a PDF response is confirmed (content_type indicates PDF and/or file signature validation) and file_size_bytes > 0.
- If an articles row exists for the requested pmid, download_pubmed_pdf must set pdf_downloads.article_id to that articles.id; otherwise it may remain NULL but pmid must still be recorded.
- For any request from a client with api_clients.status != 'active', all tools must be rejected and no new search_requests/pdf_downloads rows may be created.
- Per client, the service must enforce daily quotas: the count of search_requests created today for the two search tools must be <= daily_search_limit; the count of metadata fetch operations that resulted in an upstream call must be <= daily_metadata_limit; and the count of pdf_downloads created today must be <= daily_pdf_limit.
- All PMIDs accepted by get_pubmed_article_metadata and download_pubmed_pdf must be normalized to digits-only string form before querying or persisting.