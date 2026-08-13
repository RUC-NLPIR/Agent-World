# PubMed Article Search and Analysis Server — local MCP environment

This backend powers a PubMed-focused search and retrieval API. It stores executed searches (keyword and advanced), the resulting PubMed articles cached as metadata, and per-article PDF download attempts (including resolved full-text URLs and storage locations) to support fast repeat access and auditing.

Repository: https://github.com/geobio/PubMed-MCP-Server
Homepage: https://smithery.ai/server/@geobio/pubmed-mcp-server

## Datastore

- `api_clients.json` — Represents an API consumer (user/app). Used for rate limiting, auditability, and attribution of searches and downloads. (26 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'requests_per_minute_limit', 'daily_request_limit', 'notes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: requests_per_minute_limit >= 1 and requests_per_minute_limit <= 6000
  - constraint: daily_request_limit >= 1 and daily_request_limit <= 1000000
- `search_requests.json` — A persisted record of each search invocation (keyword or advanced), including parameters, execution status, and counts. (34 rows; fields: ['id', 'api_client_id', 'tool_name', 'key_words', 'term', 'title', 'author', 'journal', 'start_date', 'end_date', 'num_results', 'pubmed_query', 'status', 'pubmed_esearch_webenv', 'pubmed_esearch_query_key', 'result_count_total', 'result_count_returned', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: num_results >= 1 and num_results <= 500
  - constraint: tool_name in ('search_pubmed_key_words','search_pubmed_advanced')
  - constraint: ((tool_name='search_pubmed_key_words' and key_words is not null and (term is null and title is null and author is null and journal is null and start_date is null and end_date is null)) or (tool_name='search_pubmed_advanced'))
  - constraint: result_count_total is null or result_count_total >= 0
- `search_results.json` — Join table linking a search request to the PubMed articles it returned, preserving ordering/ranking and enabling fast result replay. (30 rows; fields: ['id', 'search_request_id', 'article_id', 'pmid', 'rank', 'score', 'created_at', 'updated_at'])
  - constraint: unique(search_request_id, rank)
  - constraint: unique(search_request_id, pmid)
  - constraint: rank >= 1
  - constraint: pmid > 0
- `articles.json` — Cached PubMed article metadata keyed by PMID. Populated/updated via get_pubmed_article_metadata and also opportunistically during search. (32 rows; fields: ['id', 'pmid', 'status', 'title', 'abstract', 'journal', 'publication_date', 'authors', 'doi', 'pmc_id', 'mesh_terms', 'keywords', 'source_url', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'withdrawn', 'unavailable']
  - constraint: unique(pmid)
  - constraint: pmid > 0
  - constraint: pmc_id is null or pmc_id like 'PMC%'
- `pdf_downloads.json` — Tracks attempts to resolve and download a PDF for a PubMed article (via PMC or publisher), including storage location and errors. (36 rows; fields: ['id', 'api_client_id', 'article_id', 'pmid', 'status', 'resolved_pdf_url', 'resolved_landing_url', 'storage_provider', 'storage_path', 'content_type', 'file_size_bytes', 'http_status_code', 'error_message', 'requested_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'resolving', 'downloading', 'succeeded', 'not_found', 'forbidden', 'failed']
  - constraint: pmid > 0
  - constraint: file_size_bytes is null or file_size_bytes >= 0
  - constraint: http_status_code is null or (http_status_code >= 100 and http_status_code <= 599)
  - constraint: ((status='succeeded') implies (storage_provider is not null and storage_path is not null and file_size_bytes is not null))

## Business rules enforced by the tools

- search_pubmed_key_words must create a search_requests row with tool_name='search_pubmed_key_words', key_words set, num_results defaulting to 10 when omitted, and status transitioning queued->running->(succeeded|failed).
- search_pubmed_advanced must create a search_requests row with tool_name='search_pubmed_advanced' and persist any provided filters (term,title,author,journal,start_date,end_date); at least one of these fields must be non-null for a valid advanced search.
- For any search, num_results must be clamped or rejected to the range [1, 500]; result_count_returned must not exceed num_results.
- When a search succeeds, the service must insert search_results rows for each returned PMID with contiguous rank values starting at 1, and enforce uniqueness of (search_request_id, pmid).
- get_pubmed_article_metadata(pmid) must upsert into articles by unique pmid; it must update last_fetched_at and updated_at on each successful fetch.
- download_pubmed_pdf(pmid) must ensure an articles row exists (create placeholder if missing with status='unavailable' until metadata is fetched) and create a pdf_downloads row with status='queued' and requested_at set.
- pdf_downloads status transitions must follow the declared lifecycle; setting status='succeeded' requires storage_provider, storage_path, and file_size_bytes to be non-null.
- Requests must be attributable to an active api_clients row; suspended or deleted clients must be rejected before creating search_requests or pdf_downloads.
- Rate limits must be enforced per api_client_id using requests_per_minute_limit and daily_request_limit; exceeding limits must prevent creation of new search_requests/pdf_downloads rows.