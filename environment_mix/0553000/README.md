# MinerU Document Conversion Server — local MCP environment

This backend stores document conversion jobs submitted to the MinerU Document Conversion Server and the produced parse outputs (text/structure/artifacts). It also stores the OCR language catalog exposed by the service so clients can query supported languages, and tracks server-side job lifecycle for auditing and operational controls.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@AdrianWangs/mineru-mcp

## Datastore

- `conversion_jobs.json` — Represents a document parsing/conversion request handled by the MinerU server. Each call to parse_documents creates one job even if the request contains no explicit parameters. (18 rows; fields: ['id', 'status', 'source_kind', 'source_locator', 'original_filename', 'content_type', 'size_bytes', 'sha256', 'requested_ocr_language', 'engine_version', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: status IN ('queued','running','succeeded','failed','cancelled')
  - constraint: size_bytes IS NULL OR size_bytes >= 0
  - constraint: sha256 IS NULL OR LENGTH(sha256) = 64
  - constraint: finished_at IS NULL OR started_at IS NOT NULL
- `conversion_outputs.json` — Stores the produced outputs for a conversion job, such as extracted text, structured JSON, and references to generated artifacts (e.g., images). Multiple outputs may exist per job (by type/format). (17 rows; fields: ['id', 'job_id', 'output_type', 'format', 'payload', 'payload_text', 'payload_uri', 'page_count', 'language_detected', 'created_at', 'updated_at'])
  - lifecycle `output_type`: ['text', 'structured', 'artifact_index', 'metadata', 'log']
  - constraint: FOREIGN KEY(job_id) REFERENCES conversion_jobs(id) ON DELETE CASCADE
  - constraint: UNIQUE(job_id, output_type, format)
  - constraint: page_count IS NULL OR page_count >= 0
  - constraint: (payload IS NOT NULL) OR (payload_text IS NOT NULL) OR (payload_uri IS NOT NULL)
- `job_artifacts.json` — Individual artifacts produced by a conversion job (e.g., per-page images, intermediate files). This normalizes artifact lists returned to clients and referenced by outputs. (18 rows; fields: ['id', 'job_id', 'artifact_type', 'page_number', 'uri', 'content_type', 'size_bytes', 'sha256', 'created_at', 'updated_at'])
  - lifecycle `artifact_type`: ['page_image', 'embedded_image', 'attachment', 'table_snapshot', 'debug']
  - constraint: FOREIGN KEY(job_id) REFERENCES conversion_jobs(id) ON DELETE CASCADE
  - constraint: size_bytes IS NULL OR size_bytes >= 0
  - constraint: sha256 IS NULL OR LENGTH(sha256) = 64
  - constraint: page_number IS NULL OR page_number >= 1
- `ocr_languages.json` — Catalog of OCR languages supported by the server; returned by get_ocr_languages. This can be populated from the underlying OCR engine at startup and periodically refreshed. (18 rows; fields: ['code', 'display_name', 'script', 'is_enabled', 'engine_provider', 'engine_version', 'created_at', 'updated_at'])
  - lifecycle `is_enabled`: ['true', 'false']
  - constraint: PRIMARY KEY(code)
  - constraint: UNIQUE(code)
  - constraint: display_name <> ''
  - constraint: engine_provider IN ('tesseract','paddleocr','easyocr','unknown')

## Business rules enforced by the tools

- Calling parse_documents MUST create a new conversion_jobs row with status='queued' and created_at/updated_at set to now, even if no parameters are provided by the tool surface.
- A background worker MUST transition jobs queued->running before producing any conversion_outputs or job_artifacts, and MUST set started_at when entering 'running'.
- A job may transition to succeeded only if at least one conversion_outputs row exists for that job_id.
- On succeeded/failed/cancelled, finished_at MUST be set and updated_at MUST be advanced; finished_at MUST be >= started_at when started_at is not null.
- get_ocr_languages MUST return only ocr_languages rows where is_enabled=true, and the result MUST be derivable solely from the ocr_languages collection.
- If conversion_jobs.requested_ocr_language is non-null, it MUST reference an enabled ocr_languages.code at the time the job begins running; otherwise the job MUST fail with error_code='UNSUPPORTED_LANGUAGE'.
- conversion_outputs(job_id, output_type, format) MUST be unique to prevent duplicate/conflicting outputs for the same job and representation.
- Deleting a conversion job (administrative action) MUST cascade-delete its conversion_outputs and job_artifacts to avoid orphaned records.