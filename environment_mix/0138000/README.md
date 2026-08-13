# AI Image Generation Service — local MCP environment

This backend stores tenants (workspaces), API credentials, and image generation jobs with their produced images. Main workflows: a client uses an API key to submit an image generation request (job), the system executes it against a configured model/provider, stores outputs, and exposes service metadata/documentation via a description endpoint.

Repository: https://github.com/chenyeju295/mcp_generate_images
Homepage: https://smithery.ai/server/@chenyeju295/mcp_generate_images

## Datastore

- `workspaces.json` — Tenant/workspace container for API usage, quotas, and image generation activity. (12 rows; fields: ['id', 'name', 'status', 'default_model', 'monthly_job_quota', 'monthly_image_quota', 'monthly_token_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_job_quota >= 0
  - constraint: monthly_image_quota >= 0
  - constraint: monthly_token_quota >= 0
- `api_keys.json` — API keys used to authenticate requests to the service and attribute usage to a workspace. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'key_prefix', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, workspace_id)
- `service_metadata.json` — Versioned metadata and documentation for the service used by the use_description tool. (12 rows; fields: ['id', 'service_name', 'repository_url', 'description_markdown', 'tool_surface', 'status', 'published_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'archived']
  - constraint: unique(status) WHERE status = 'published'
- `image_generation_jobs.json` — A single image generation request, from submission through completion/failure, used by generate_image. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'idempotency_key', 'prompt', 'negative_prompt', 'model', 'provider', 'request_params', 'requested_image_count', 'status', 'error_code', 'error_message', 'queued_at', 'started_at', 'finished_at', 'billed_tokens', 'billed_cost_usd', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: requested_image_count >= 1
  - constraint: requested_image_count <= 10
  - constraint: billed_tokens >= 0
  - constraint: billed_cost_usd >= 0
- `generated_images.json` — Individual images produced by an image generation job (may be multiple per job). (18 rows; fields: ['id', 'job_id', 'workspace_id', 'index_in_job', 'status', 'mime_type', 'width', 'height', 'seed', 'storage_backend', 'storage_uri', 'sha256', 'created_at', 'updated_at'])
  - lifecycle `status`: ['stored', 'deleted']
  - constraint: unique(job_id, index_in_job)
  - constraint: index_in_job >= 0
  - constraint: width IS NULL OR width > 0
  - constraint: height IS NULL OR height > 0

## Business rules enforced by the tools

- use_description returns the single service_metadata record with status='published'; if none exists, it returns the most recently updated draft.
- generate_image creates an image_generation_jobs row with status='queued' (or directly 'running' for synchronous execution) and persists request_params even when the tool schema is empty (e.g., server-side defaults and/or extended inputs).
- If idempotency_key is provided, generate_image must return the existing job for the same (workspace_id, idempotency_key) instead of creating a new one.
- A workspace in status 'suspended' or 'deleted' cannot create new image_generation_jobs.
- An api_key in status 'revoked' cannot create new jobs; attempts must be rejected and must not mutate job tables.
- On job completion: status must transition to 'succeeded' only if at least 1 generated_images row is created and stored_uri is non-empty for each output; otherwise the job must be 'failed'.
- requested_image_count must be enforced between 1 and 10 inclusive; the number of generated_images rows created for a succeeded job must equal requested_image_count.
- Monthly quotas must be enforced per workspace: count(image_generation_jobs.created_at within month) <= monthly_job_quota and count(generated_images.created_at within month) <= monthly_image_quota and sum(image_generation_jobs.billed_tokens within month) <= monthly_token_quota.
- billed_tokens and billed_cost_usd are immutable once a job reaches a terminal state (succeeded/failed/cancelled).
- Cancelling a job is only allowed from status in ('queued','running'); cancellation must end in status='cancelled' and set finished_at.
- Deleting an image output sets generated_images.status='deleted' and must not remove the parent job record; physical deletion of bytes is handled asynchronously by storage_backend policies.