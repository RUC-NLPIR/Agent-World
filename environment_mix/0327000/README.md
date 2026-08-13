# Jimeng AI Image Generation Server — local MCP environment

This backend stores accounts, API keys, image generation jobs, and generated image artifacts for the Jimeng AI Image Generation Server. The primary workflow is: an authenticated client submits a generation request (with defaults if no parameters are provided), the system enqueues/runs a job, and stores output images and job metadata for later retrieval and auditing.

Repository: https://github.com/huangmiuXyz/jimeng-mcp
Homepage: https://smithery.ai/server/@huangmiuXyz/jimeng-mcp

## Datastore

- `accounts.json` — Represents an owning identity (user/org) that holds API keys and owns image generation jobs and artifacts. (12 rows; fields: ['id', 'display_name', 'email', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(email) where email is not null
  - constraint: display_name != ''
- `api_keys.json` — API credentials used to authenticate calls to generate images and to apply quotas/rate limits. (11 rows; fields: ['id', 'account_id', 'key_prefix', 'key_hash', 'name', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_prefix)
  - constraint: unique(account_id, name)
  - constraint: key_prefix != ''
  - constraint: key_hash != ''
- `generation_jobs.json` — Represents a single image generation request execution. The public tool surface has no parameters, so jobs are created with server-side defaults and configuration captured in this record for reproducibility and audit. (12 rows; fields: ['id', 'account_id', 'api_key_id', 'status', 'provider', 'input', 'resolved_defaults_version', 'attempt', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: attempt >= 1
  - constraint: provider in ('jimeng')
  - constraint: status in ('queued','running','succeeded','failed','cancelled')
  - constraint: finished_at is null when status in ('queued','running')
- `generated_images.json` — Stores output image artifacts produced by a generation job, including storage pointers and basic metadata. (12 rows; fields: ['id', 'job_id', 'account_id', 'status', 'content_type', 'byte_size', 'width', 'height', 'storage_backend', 'storage_bucket', 'storage_key', 'sha256', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted']
  - constraint: byte_size >= 0
  - constraint: width is null or width > 0
  - constraint: height is null or height > 0
  - constraint: unique(storage_backend, storage_bucket, storage_key)
- `usage_counters.json` — Tracks per-account and per-api-key usage for quota enforcement and operational monitoring (e.g., jobs/day, images/day). (11 rows; fields: ['id', 'account_id', 'api_key_id', 'period_start', 'period_granularity', 'jobs_created', 'images_generated', 'failed_jobs', 'created_at', 'updated_at'])
  - constraint: jobs_created >= 0
  - constraint: images_generated >= 0
  - constraint: failed_jobs >= 0
  - constraint: unique(account_id, api_key_id, period_start, period_granularity)

## Business rules enforced by the tools

- generateImage must authenticate using an active api_keys row whose status='active' and whose accounts.status='active'.
- generateImage must create a generation_jobs row with status='queued' (or 'running' if executed synchronously), provider='jimeng', attempt=1, and input populated from server defaults because the tool exposes no parameters.
- A generation_jobs row may transition only according to generation_jobs.lifecycle.transitions; terminal statuses are succeeded/failed/cancelled.
- On job success, at least one generated_images row must be created referencing the job_id; generated_images.account_id must equal generation_jobs.account_id.
- On job failure, generation_jobs.error_code and generation_jobs.error_message must be non-null and generated_images rows must not be created (or must be marked deleted if partially created).
- usage_counters must be incremented atomically with job creation and job completion: jobs_created increments on creation; images_generated increments by the number of generated_images created when the job succeeds; failed_jobs increments when a job reaches failed.
- Quota enforcement: if usage_counters.jobs_created for (account_id, null, current day) exceeds an account-level limit, generateImage must reject job creation; similarly for api_key_id-specific limits when api_key_id is present.
- API key revocation must prevent new generation_jobs creation, but must not delete historical generation_jobs or generated_images records.