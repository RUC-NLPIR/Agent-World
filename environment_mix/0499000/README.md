# Law Tool KOR — local MCP environment

This backend supports searching Korean law resources for PDF documents and loading/processing those PDFs. It stores search requests, discovered PDF URLs, PDF fetch/parse jobs, and the extracted text content for downstream use.

Repository: https://github.com/drepion43/law_tool_KOR
Homepage: https://smithery.ai/server/@drepion43/law_tool_kor

## Datastore

- `search_queries.json` — Normalized log of user search inputs for finding Korean law PDF resources; used by pdf_url and as an entry-point for subsequent PDF loading. (18 rows; fields: ['id', 'query_text', 'query_hash', 'normalized_query_text', 'status', 'result_count', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'searching', 'completed', 'failed']
  - constraint: unique(query_hash)
  - constraint: length(query_text) between 1 and 512
  - constraint: result_count >= 0
- `pdf_candidates.json` — PDF URLs discovered for a given search query, including basic metadata and ranking. Primary data returned by pdf_url. (18 rows; fields: ['id', 'search_query_id', 'url', 'url_hash', 'source_host', 'title', 'rank', 'status', 'http_status_last', 'content_type_last', 'content_length_last_bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['discovered', 'filtered', 'fetch_scheduled', 'fetched', 'fetch_failed']
  - constraint: foreign key(search_query_id) references search_queries(id) on delete cascade
  - constraint: unique(search_query_id, url_hash)
  - constraint: rank >= 1
  - constraint: content_length_last_bytes is null or content_length_last_bytes >= 0
- `pdf_documents.json` — Canonical representation of a PDF resource (deduplicated across queries) and its fetched bytes metadata; used by load_pdf to retrieve/parse content. (18 rows; fields: ['id', 'canonical_url', 'canonical_url_hash', 'status', 'etag', 'last_modified', 'sha256_bytes', 'byte_size', 'stored_object_key', 'last_fetch_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['new', 'fetching', 'available', 'unavailable']
  - constraint: unique(canonical_url_hash)
  - constraint: byte_size is null or byte_size >= 0
  - constraint: sha256_bytes is null or length(sha256_bytes) = 64
- `pdf_load_jobs.json` — Execution records for load_pdf requests; ties a user query to a specific URL/PDF document and tracks fetch+parse outcomes. (20 rows; fields: ['id', 'input_query_text', 'search_query_id', 'pdf_candidate_id', 'pdf_document_id', 'resolved_url', 'status', 'failure_stage', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'parsing', 'completed', 'failed']
  - constraint: length(input_query_text) between 1 and 2048
  - constraint: failure_stage is null or status = 'failed'
  - constraint: foreign key(search_query_id) references search_queries(id) on delete set null
  - constraint: foreign key(pdf_candidate_id) references pdf_candidates(id) on delete set null
- `pdf_extractions.json` — Extracted text and structural metadata from a PDF document. load_pdf reads/writes here to return parsed content quickly on subsequent calls. (18 rows; fields: ['id', 'pdf_document_id', 'load_job_id', 'status', 'page_count', 'language', 'text_content', 'text_storage_key', 'extract_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'extracting', 'ready', 'failed']
  - constraint: foreign key(pdf_document_id) references pdf_documents(id) on delete cascade
  - constraint: foreign key(load_job_id) references pdf_load_jobs(id) on delete set null
  - constraint: unique(pdf_document_id)
  - constraint: page_count is null or page_count >= 0

## Business rules enforced by the tools

- pdf_url(query): must create or upsert a search_queries row keyed by query_hash; it then populates pdf_candidates for that search_query_id and sets search_queries.status to completed or failed.
- pdf_url(query): must enforce unique(search_query_id, url_hash) for discovered candidates; ranks must be consecutive starting at 1 for each search_query_id.
- load_pdf(query): must create a pdf_load_jobs row with input_query_text=query and status=queued, then resolve the query to a URL. If query matches an existing pdf_candidates.url (exact or canonical match), it should link pdf_candidate_id and search_query_id when available.
- load_pdf(query): must upsert pdf_documents by canonical_url_hash; multiple load jobs may reference the same pdf_document_id.
- A pdf_document may transition to available only after stored_object_key and sha256_bytes are set (and byte_size is non-null).
- When a pdf_load_jobs row reaches completed, there must exist a pdf_extractions row with status=ready for its pdf_document_id (either created by that job or already present).
- If pdf_extractions.text_content exceeds the configured inline limit (e.g., 1-5 MB), the implementation must store content externally and set text_storage_key; status=ready requires at least one of text_content or text_storage_key.
- On failed load_pdf executions, pdf_load_jobs.status must be failed and failure_stage must be non-null; error_message must be populated.
- FK integrity must be enforced: deleting a search_query cascades to its pdf_candidates; deleting a pdf_document cascades to its pdf_extractions.