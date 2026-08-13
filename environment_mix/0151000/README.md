# Document Reader — local MCP environment

This backend stores ingested document files (PDF/EPUB), their extracted metadata, and normalized page/chapter text to support reading page ranges and full-text search. Core workflows are: register/import a document from a local/remote path, extract metadata and paginated text, then serve read and search requests while tracking request history and enforcing basic integrity constraints.

Repository: https://github.com/jbchouinard/mcp-document-reader
Homepage: https://smithery.ai/server/@jbchouinard/mcp-document-reader

## Datastore

- `documents.json` — Represents a registered document (PDF or EPUB) known to the service. Stores the source path/URI used by tools, basic identity, and ingestion lifecycle. (18 rows; fields: ['id', 'doc_type', 'source_path', 'source_path_hash', 'filename', 'title', 'author', 'language', 'page_count', 'file_size_bytes', 'sha256', 'status', 'ingest_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['registered', 'ingesting', 'ready', 'error', 'deleted']
  - constraint: unique(doc_type, source_path_hash)
  - constraint: page_count is null OR page_count >= 0
  - constraint: file_size_bytes is null OR file_size_bytes >= 0
  - constraint: sha256 is null OR length(sha256) = 64
- `document_metadata.json` — Key/value metadata extracted from a document. Used to format tool outputs for get_pdf_metadata and get_epub_metadata. (17 rows; fields: ['id', 'document_id', 'namespace', 'key', 'value', 'value_json', 'created_at', 'updated_at'])
  - lifecycle `namespace`: ['pdf', 'epub', 'dc', 'opf', 'xmp', 'custom']
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: unique(document_id, namespace, key)
- `document_pages.json` — Normalized per-page extracted text for PDFs and EPUBs (EPUB pages may be computed/virtual). Supports read_* and search_* tools. (17 rows; fields: ['id', 'document_id', 'page_number', 'label', 'text', 'text_length', 'status', 'extract_error', 'source_ref', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'extracted', 'error']
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: unique(document_id, page_number)
  - constraint: page_number >= 1
  - constraint: text_length >= 0
- `search_requests.json` — Stores search operations executed against a document for auditability, caching, and troubleshooting. Powers search_pdf and search_epub. (18 rows; fields: ['id', 'document_id', 'terms_raw', 'terms_normalized', 'match_mode', 'status', 'result_pages_count', 'execution_ms', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: terms_raw <> ''
  - constraint: array_length(terms_normalized) >= 1
  - constraint: execution_ms is null OR execution_ms >= 0
- `search_results.json` — Per-page results for a search request: which page matched and which terms were found. Returned by search_pdf/search_epub formatted into a string. (17 rows; fields: ['id', 'search_request_id', 'document_id', 'page_number', 'matched_terms', 'match_count', 'snippet', 'created_at', 'updated_at'])
  - lifecycle `match_count`: []
  - constraint: foreign key(search_request_id) references search_requests(id) on delete cascade
  - constraint: foreign key(document_id) references documents(id) on delete cascade
  - constraint: unique(search_request_id, page_number)
  - constraint: page_number >= 1

## Business rules enforced by the tools

- For get_pdf_metadata(pdf_path): the implementation must resolve pdf_path to documents.source_path (doc_type='pdf'); if no documents row exists, it must create one with status='registered', then ingest metadata into document_metadata and transition documents.status to 'ready' or 'error'.
- For get_epub_metadata(epub_path): the implementation must resolve epub_path to documents.source_path (doc_type='epub'); if missing, create documents row and ingest metadata similarly.
- For read_pdf_pages(pdf_path, pages) and read_pdf_page_range(pdf_path, start_page, end_page): the service must ensure the target document exists and is status='ready' before reading; requested page numbers must be within [1, documents.page_count] when page_count is known; otherwise it must reject or trigger ingestion and return an error until ready.
- For read_epub_pages(epub_path, pages) and read_epub_page_range(epub_path, start_page, end_page): the service must ensure the document exists and is status='ready'; requested page numbers must be >= 1 and must exist in document_pages for that document.
- For any read_* tool: pages must be unique and sorted in the formatted output; missing pages (no document_pages row or status!='extracted') must either be omitted with an explicit placeholder or cause the request to fail consistently (service-wide policy).
- For search_pdf(pdf_path, terms) and search_epub(epub_path, terms): the implementation must create a search_requests row, normalize terms into search_requests.terms_normalized (split on commas, trim, drop empties, dedupe), then scan document_pages.text for matches and write per-page matches to search_results; upon completion set search_requests.status='succeeded' and populate result_pages_count.
- search_requests.status transitions must follow the declared lifecycle; once 'succeeded' or 'failed', results are immutable (no further inserts/updates to search_results for that search_request_id).
- documents(doc_type, source_path_hash) must be unique; repeated calls with the same path and type must reuse the same documents row rather than creating duplicates.
- Deleting a document (documents.status='deleted') must cascade-delete document_metadata, document_pages, search_requests, and search_results rows via FK rules or equivalent application logic.