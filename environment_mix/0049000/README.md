# Image Analysis Server — local MCP environment

This backend stores image-analysis requests submitted to the Image Analysis Server, the images referenced/ingested for analysis, and the resulting model outputs. Main workflows are: create an analysis job (either from an uploaded image or a server-local file path), execute it with a vision model, store outputs, and track usage for operational limits.

Repository: https://github.com/champierre/image-mcp-server
Homepage: https://smithery.ai/server/@champierre/image-mcp-server

## Datastore

- `api_keys.json` — API credentials used to authenticate callers and apply quotas/rate limits to image analysis requests. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'quota_day_requests', 'quota_day_images', 'quota_day_tokens', 'rate_limit_rpm', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: quota_day_requests >= 0
  - constraint: quota_day_images >= 0
  - constraint: quota_day_tokens >= 0
- `images.json` — Images referenced by analysis jobs, either uploaded/attached or referenced by server-local filesystem path. (18 rows; fields: ['id', 'source_type', 'local_path', 'storage_url', 'sha256', 'mime_type', 'byte_size', 'width', 'height', 'created_at', 'updated_at'])
  - lifecycle `source_type`: ['upload', 'local_path']
  - constraint: source_type in ('upload','local_path')
  - constraint: source_type = 'local_path' implies local_path is not null
  - constraint: source_type = 'upload' implies storage_url is not null
  - constraint: byte_size is null or byte_size >= 0
- `analysis_jobs.json` — A single request to analyze an image. This directly backs the analyze_image and analyze_image_from_path tools, which create jobs and return the stored output. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'image_id', 'status', 'model', 'request_context', 'result_text', 'result_json', 'error_code', 'error_message', 'tokens_input', 'tokens_output', 'latency_ms', 'created_at', 'updated_at', 'started_at', 'finished_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: tool_name in ('analyze_image','analyze_image_from_path')
  - constraint: model = 'gpt-4o-mini'
  - constraint: tokens_input is null or tokens_input >= 0
  - constraint: tokens_output is null or tokens_output >= 0
- `usage_daily.json` — Per-API-key daily usage aggregates used to enforce quotas for analysis jobs. (17 rows; fields: ['id', 'api_key_id', 'usage_date', 'requests_count', 'images_count', 'tokens_input', 'tokens_output', 'created_at', 'updated_at'])
  - lifecycle `usage_date`: ['date_bucket']
  - constraint: unique(api_key_id, usage_date)
  - constraint: requests_count >= 0
  - constraint: images_count >= 0
  - constraint: tokens_input >= 0

## Business rules enforced by the tools

- Calling analyze_image creates an images row with source_type='upload' (or equivalent in-memory ingestion persisted to storage_url) and then creates an analysis_jobs row with tool_name='analyze_image'.
- Calling analyze_image_from_path must create an images row with source_type='local_path' and local_path populated, then creates an analysis_jobs row with tool_name='analyze_image_from_path'.
- For analyze_image_from_path, local_path must be an absolute, normalized path in the server runtime OS and must pass an allowlist/deniedlist policy (e.g., deny /proc, /sys, /dev, and traversal '..'); otherwise the job is created as failed with error_code='IMAGE_LOAD_FAILED' (or rejected before job creation depending on implementation).
- An analysis_jobs row must reference an existing images row (FK integrity) and may reference an api_keys row; if api_key_id is provided it must reference an api_keys row with status='active'.
- Before transitioning a job from queued->running, the service must verify api key rate limits (rate_limit_rpm) and daily quotas (quota_day_requests, quota_day_images, quota_day_tokens) using usage_daily; if exceeded, the job must fail with error_code='QUOTA_EXCEEDED' (or be rejected before creation).
- On job completion (succeeded/failed/cancelled), finished_at must be set and latency_ms computed as finished_at-started_at when started_at exists.
- If a job status is succeeded, at least one of result_text or result_json must be non-null and error_code must be null.
- If a job status is failed, error_code must be set and result_text/result_json may be null; error_message may be stored for debugging but must not contain raw secrets or full local file contents.
- usage_daily must be upserted per (api_key_id, usage_date) whenever an analysis job is created/completed; counters must never decrease and must reflect successful admission (created) rather than only successful completion, depending on quota policy.