# Gemini Imagen 3.0 Image Generation Server — local MCP environment

This backend stores image-generation jobs executed against Gemini Imagen 3.0, the resulting image artifacts (file paths/metadata), and derived HTML gallery renderings created from stored image paths. The primary workflows are: create/execute a generation request, persist outputs and job status; then build and persist an HTML snippet (gallery) referencing one or more stored images.

Repository: https://github.com/falahgs/imagen-3.0-generate-google-mcp-server
Homepage: https://smithery.ai/server/@falahgs/imagen-3-0-generate-google-mcp-server

## Datastore

- `workspaces.json` — Logical tenant boundary for grouping image generation activity and outputs. Even if the tool surface is parameterless, a real production system needs a default workspace to attach jobs and artifacts to. (12 rows; fields: ['id', 'name', 'status', 'default_model', 'storage_base_path', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: storage_base_path <> ''
- `api_keys.json` — API keys used to authenticate callers and to enforce quotas/rate limits. The tool surface does not expose key management, but production deployments typically require it for any public API server. (12 rows; fields: ['id', 'workspace_id', 'key_hash', 'name', 'status', 'requests_per_minute_limit', 'daily_job_limit', 'daily_image_limit', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit between 1 and 6000
  - constraint: daily_job_limit between 0 and 100000
- `image_generation_jobs.json` — A single invocation of the generate_images tool, tracked as an asynchronous job with persisted request/response metadata and status transitions. (34 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'model', 'request_payload', 'response_payload', 'provider_request_id', 'error_code', 'error_message', 'queued_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: model = 'gemini-imagen-3.0'
  - constraint: finished_at is null when status in ('queued','running')
  - constraint: started_at is not null when status in ('running','succeeded','failed','cancelled') and status <> 'queued'
  - constraint: error_code is not null when status = 'failed'
- `image_artifacts.json` — Generated image files stored on disk (or mounted storage) produced by a job. These rows back the create_image_html tool by providing canonical file paths and metadata. (34 rows; fields: ['id', 'workspace_id', 'job_id', 'status', 'file_path', 'file_name', 'mime_type', 'byte_size', 'width', 'height', 'sha256', 'sort_order', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['available', 'deleted']
  - constraint: unique(workspace_id, file_path)
  - constraint: unique(job_id, sort_order)
  - constraint: byte_size >= 0
  - constraint: sort_order >= 0
- `html_galleries.json` — Persisted HTML outputs created by the create_image_html tool. A gallery references one or more stored image_artifacts and stores the generated HTML snippet for re-use. (15 rows; fields: ['id', 'workspace_id', 'status', 'title', 'image_paths', 'html', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: json_array_length(image_paths) between 1 and 200
  - constraint: html <> ''
  - constraint: deleted_at is not null when status = 'deleted'
  - constraint: deleted_at is null when status = 'active'

## Business rules enforced by the tools

- Every generate_images call creates exactly one image_generation_jobs row and transitions status from queued -> running -> (succeeded|failed|cancelled).
- On job success, at least one image_artifacts row must exist for the job and all must have status=available; on job failure, no available artifacts may be created (any partially written files must be marked deleted).
- create_image_html must generate HTML only for file paths that exist as image_artifacts.file_path in the same workspace and have status=available; otherwise it must fail validation.
- If an api_key is provided, the server must enforce requests_per_minute_limit and daily_job_limit on generate_images, and daily_image_limit based on the number of image_artifacts created per day.
- api_keys.status=revoked cannot be used to create new jobs or galleries.
- workspaces.status=suspended forbids new job execution (jobs may be created as queued but must not transition to running) and forbids new galleries; workspaces.status=deleted forbids all writes.
- image_artifacts.file_path must be unique per workspace and must be rooted under workspaces.storage_base_path to prevent path traversal and cross-tenant access.
- A gallery's image_paths ordering must be preserved in the produced html and must match the persisted image_paths array.