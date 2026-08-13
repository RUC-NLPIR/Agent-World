# Mistral OCR — local MCP environment

This backend stores OCR processing jobs submitted either from a local file (restricted to a configured OCR_DIR) or from a remote URL, and persists the extracted text plus processing metadata. Main workflows are: accept a source (local path or URL), create a job, fetch/validate the document, run OCR, store results, and expose job history/outputs for debugging and operational visibility.

Repository: https://github.com/everaldo/mcp-mistral-ocr
Homepage: https://smithery.ai/server/@everaldo/mcp-mistral-ocr

## Datastore

- `api_keys.json` — API keys allowed to submit OCR jobs. Used for authentication, rate limiting, and attribution of usage. (12 rows; fields: ['id', 'key_hash', 'name', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(name)
  - constraint: status in ('active','revoked')
- `ocr_jobs.json` — A single OCR processing request for either a local file (from OCR_DIR) or a URL. Tracks lifecycle, validation, and processor metadata. (18 rows; fields: ['id', 'api_key_id', 'source_type', 'local_rel_path', 'url', 'original_filename', 'content_type', 'input_bytes', 'sha256', 'status', 'error_code', 'error_message', 'processor', 'processor_version', 'queued_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'processing', 'succeeded', 'failed', 'cancelled']
  - constraint: source_type in ('local_file','url')
  - constraint: processor = 'mistral_ocr'
  - constraint: ((source_type = 'local_file' and local_rel_path is not null and url is null) or (source_type = 'url' and url is not null and local_rel_path is null))
  - constraint: input_bytes is null or input_bytes >= 0
- `ocr_outputs.json` — OCR results produced by an OCR job, including extracted text, optional structured blocks, and per-page summaries. (18 rows; fields: ['id', 'job_id', 'result_format', 'language_hint', 'page_count', 'text', 'structured', 'created_at', 'updated_at'])
  - constraint: unique(job_id)
  - constraint: result_format in ('plain_text','markdown','json')
  - constraint: page_count is null or page_count >= 0
  - constraint: (result_format != 'json' and text is not null) or (result_format = 'json')
- `stored_files.json` — Materialized copies of source files (downloaded from URL or referenced local file metadata) for reproducibility, deduplication, and reprocessing. (18 rows; fields: ['id', 'job_id', 'storage_backend', 'storage_path', 'content_type', 'bytes', 'sha256', 'created_at', 'updated_at'])
  - constraint: unique(sha256, bytes)
  - constraint: bytes >= 0
  - constraint: length(sha256) = 64
  - constraint: storage_backend in ('local_fs','object_store')
- `request_logs.json` — Operational log of tool invocations (list_tools, process_local_file, process_url_file) for debugging, auditing and usage tracking. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'job_id', 'status', 'http_status', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'error']
  - constraint: tool_name in ('list_tools','process_local_file','process_url_file')
  - constraint: status in ('ok','error')
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: (tool_name = 'list_tools' and job_id is null) or (tool_name in ('process_local_file','process_url_file'))

## Business rules enforced by the tools

- The list_tools tool must only read static tool metadata and must write a request_logs row with tool_name='list_tools'.
- The process_local_file tool must create an ocr_jobs row with source_type='local_file' and a non-null local_rel_path; local_rel_path must be validated to remain within OCR_DIR (no absolute paths, no '..' traversal).
- The process_url_file tool must create an ocr_jobs row with source_type='url' and a non-null url; the url must be validated to be http/https and normalized for storage.
- For any processing tool invocation, a request_logs row must be created and linked to the corresponding ocr_jobs.id (job_id) once created.
- An ocr_jobs row may transition only through the declared lifecycle transitions; once status is in ('succeeded','failed','cancelled') it is terminal and must not change.
- On successful completion of a job (status='succeeded'), exactly one ocr_outputs row must exist for that job and exactly one stored_files row must exist for that job; both must reference the same job_id.
- If a job fails (status='failed'), ocr_outputs must not be created unless partial results are explicitly supported; if partial results are stored, error_code must be set and ocr_outputs.result_format must be 'json' with structured containing a partial flag.
- Deduplication: if a new input has the same sha256 and bytes as an existing stored_files row, the system may reuse the existing stored object, but must still create a new ocr_jobs row and a new ocr_outputs row (unless serving from cache is explicitly enabled).
- If api_key_id is present on an ocr_jobs row, it must reference an api_keys row with status='active'; revoked keys must be rejected at submission time.
- input_bytes must not exceed a configured maximum size; jobs violating the limit must be marked failed with error_code='file_too_large'.
- Only supported content types (e.g., application/pdf and common image types) may proceed to processing; unsupported types must fail with error_code='unsupported_type'.