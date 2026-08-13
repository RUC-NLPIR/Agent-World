# AI Agent with MCP — local MCP environment

This backend stores tool invocations for an MCP-based AI agent, including hello responses, user-list fetches from an external API, and document/image analysis requests sent to AWS Textract. The main workflows are: record each tool call, optionally cache external responses (users list) for reuse, and track Textract jobs from file submission through completion/error with extracted results.

Repository: https://github.com/moises-paschoalick/ai-agent-with-mcp
Homepage: https://smithery.ai/server/@moises-paschoalick/ai-agent-with-mcp

## Datastore

- `tool_invocations.json` — Append-only-ish log of every tool call made through the MCP agent, including inputs, outputs, timing, and errors. Serves as the audit trail and can be used for debugging, analytics, and replay. (36 rows; fields: ['id', 'tool_name', 'request_params', 'normalized_file_path', 'status', 'response_payload', 'error_code', 'error_message', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: tool_name in ('Hello Tool','Users Tool','Textract Tool')
  - constraint: status in ('received','running','succeeded','failed')
  - constraint: request_params is valid JSON object
  - constraint: tool_name != 'Textract Tool' OR request_params.filePath is not null
- `external_user_fetches.json` — Tracks each fetch to the external Users API and optionally stores the response for caching and auditing. Tied to a Users Tool invocation. (12 rows; fields: ['id', 'invocation_id', 'provider', 'request_url', 'http_status', 'response_body', 'etag', 'fetched_at', 'cache_key', 'cache_ttl_seconds', 'cache_expires_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['attempted', 'succeeded', 'failed']
  - constraint: FK(invocation_id) references tool_invocations(id) on delete cascade
  - constraint: unique(invocation_id)
  - constraint: provider in ('jsonplaceholder','unknown')
  - constraint: cache_ttl_seconds >= 0 and cache_ttl_seconds <= 86400
- `textract_jobs.json` — Represents a Textract analysis request initiated by Textract Tool. Stores the source file path, request/response metadata, and job status. (12 rows; fields: ['id', 'invocation_id', 'file_path', 'file_sha256', 'content_type', 'file_size_bytes', 'textract_mode', 'aws_region', 'aws_request_id', 'status', 'submitted_at', 'completed_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'uploading', 'processing', 'succeeded', 'failed']
  - constraint: FK(invocation_id) references tool_invocations(id) on delete cascade
  - constraint: unique(invocation_id)
  - constraint: textract_mode in ('analyze_document','detect_document_text')
  - constraint: file_path <> ''
- `textract_results.json` — Stores parsed/normalized outputs from Textract for a given job, plus the raw response blob for replay/debugging. Split out so jobs remain lightweight and results can be versioned. (12 rows; fields: ['id', 'textract_job_id', 'result_version', 'raw_response', 'extracted_text', 'blocks', 'confidence_avg', 'created_at', 'updated_at'])
  - lifecycle `result_version`: [1]
  - constraint: FK(textract_job_id) references textract_jobs(id) on delete cascade
  - constraint: unique(textract_job_id, result_version)
  - constraint: result_version >= 1
  - constraint: confidence_avg is null OR (confidence_avg >= 0 AND confidence_avg <= 100)

## Business rules enforced by the tools

- A tool invocation must be created for every tool execution, with tool_name exactly matching one of the exposed tool names.
- Hello Tool invocations must have request_params = {} and on success response_payload contains a string hello message.
- Users Tool invocations must have request_params = {}; execution must create exactly one external_user_fetches row linked by invocation_id.
- Users Tool may return a cached response only if an external_user_fetches row exists with the same cache_key and cache_expires_at > now(); otherwise a new fetch is attempted and stored.
- Textract Tool invocations must include request_params.filePath; execution must create exactly one textract_jobs row linked by invocation_id.
- Textract Tool must fail with error_code = FILE_NOT_FOUND if the given file_path cannot be read from the local filesystem at execution time.
- A textract_jobs row may only transition forward along the declared lifecycle; once succeeded or failed it is immutable except for updated_at and attaching results.
- A textract_results row may only be created when the associated textract_jobs.status = 'succeeded'.
- For any invocation marked succeeded, response_payload must be non-null and error_code/error_message must be null; for failed, response_payload must be null and error_message must be non-null.
- finished_at and duration_ms must be set when status becomes succeeded or failed; duration_ms must equal (finished_at - started_at) in milliseconds within an acceptable tolerance.