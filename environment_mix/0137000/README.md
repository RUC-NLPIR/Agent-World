# Video Generation Server with Google Veo2 — local MCP environment

This backend stores user/workspace-scoped media generation jobs and the resulting assets (images and videos) produced via Google Imagen and Google Veo2. Core workflows: submit a generation request (text->video, image->video, text->image, or text->image->video), track job lifecycle, persist outputs and allow listing and retrieval of generated media.

Repository: https://github.com/mario-andreschak/mcp-veo2
Homepage: https://smithery.ai/server/@mario-andreschak/mcp-veo2

## Datastore

- `workspaces.json` — Tenant boundary for requests and generated assets. Used to scope listing endpoints and enforce quotas. (12 rows; fields: ['id', 'name', 'status', 'plan', 'quota_daily_video_seconds', 'quota_daily_image_count', 'quota_daily_job_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: quota_daily_video_seconds >= 0
  - constraint: quota_daily_image_count >= 0
  - constraint: quota_daily_job_count >= 0
- `api_keys.json` — API keys used by clients to access the server and associate requests to a workspace; supports key rotation and revocation. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
- `generation_jobs.json` — Canonical record of each generation request submitted to the system, including input modality (text or image), model/provider selection, and lifecycle tracking. Each job can produce zero or more media outputs. (36 rows; fields: ['id', 'workspace_id', 'api_key_id', 'job_type', 'provider', 'model', 'prompt_text', 'input_image_id', 'intermediate_image_id', 'requested_video_seconds', 'requested_fps', 'requested_width', 'requested_height', 'seed', 'status', 'error_code', 'error_message', 'provider_operation_id', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: requested_video_seconds is null OR (requested_video_seconds >= 1 AND requested_video_seconds <= 60)
  - constraint: requested_fps is null OR (requested_fps >= 1 AND requested_fps <= 60)
  - constraint: requested_width is null OR requested_width >= 64
  - constraint: requested_height is null OR requested_height >= 64
- `images.json` — Generated (or imported) image assets. Supports listing and lookup by ID for getImage and listGeneratedImages. (29 rows; fields: ['id', 'workspace_id', 'job_id', 'source', 'provider', 'model', 'prompt_text', 'width', 'height', 'mime_type', 'byte_size', 'storage_bucket', 'storage_key', 'sha256', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted']
  - constraint: width >= 1
  - constraint: height >= 1
  - constraint: byte_size >= 0
  - constraint: unique(workspace_id, storage_bucket, storage_key)
- `videos.json` — Generated video assets produced by Veo2. Supports listing via listGeneratedVideos and association back to the originating job. (19 rows; fields: ['id', 'workspace_id', 'job_id', 'provider', 'model', 'prompt_text', 'source_image_id', 'duration_seconds', 'fps', 'width', 'height', 'mime_type', 'byte_size', 'storage_bucket', 'storage_key', 'sha256', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted']
  - constraint: duration_seconds >= 1 AND duration_seconds <= 600
  - constraint: byte_size >= 0
  - constraint: unique(workspace_id, storage_bucket, storage_key)
  - constraint: sha256 is null OR unique(workspace_id, sha256)
- `usage_ledger.json` — Append-only ledger of billable/quota-relevant usage per job. Used to enforce daily workspace quotas and support future billing/auditing. (32 rows; fields: ['id', 'workspace_id', 'job_id', 'usage_type', 'quantity', 'occurred_on', 'created_at', 'updated_at'])
  - lifecycle `usage_type`: ['job', 'image', 'video_second']
  - constraint: quantity > 0
  - constraint: unique(job_id, usage_type)
  - constraint: usage_type IN ('job','image','video_second')

## Business rules enforced by the tools

- Every tool call authenticates via an api_key that must be status='active' and belong to a workspace with status='active'.
- generateVideoFromText creates a generation_jobs row with job_type='text_to_video', model='veo2', provider='google', status='queued', prompt_text required, and requested_video_seconds set to a server default if not specified by the implementation.
- generateVideoFromImage creates a generation_jobs row with job_type='image_to_video', model='veo2', provider='google', status='queued', input_image_id required and must reference an images row with status='available' in the same workspace.
- generateImage creates a generation_jobs row with job_type='text_to_image', model='imagen', provider='google', status='queued', prompt_text required; upon success it must create exactly one images row linked by images.job_id and set job status='succeeded'.
- generateVideoFromGeneratedImage creates a generation_jobs row with job_type='text_to_image_to_video'; it may create an intermediate images row (images.job_id referencing the same job and also referenced by generation_jobs.intermediate_image_id) before creating at least one videos row for the same job.
- listGeneratedVideos returns videos rows for the authenticated workspace where status='available', ordered by created_at desc.
- listGeneratedImages returns images rows for the authenticated workspace where status='available', ordered by created_at desc.
- getImage(id) returns the images row only if it belongs to the authenticated workspace and status='available'; otherwise it behaves as not found.
- A generation_jobs row may transition status only according to generation_jobs.lifecycle.transitions; terminal states are immutable (no further transitions).
- When a job is created, the system must append usage_ledger records: always one usage_type='job' with quantity=1; for successful image outputs one usage_type='image' per job with quantity equal to number of images produced; for successful video outputs one usage_type='video_second' per job with quantity equal to sum(duration_seconds) of videos produced.
- Before enqueuing a new job (status='queued'), the system must ensure that daily rollups over usage_ledger for the workspace do not exceed workspace quotas: sum(video_second.quantity) <= quota_daily_video_seconds, sum(image.quantity) <= quota_daily_image_count, sum(job.quantity) <= quota_daily_job_count; otherwise the job must be rejected or created directly with status='failed' and error_code='quota_exceeded'.
- All assets (images/videos) must belong to the same workspace as their originating job; inserts violating workspace consistency must be rejected.
- Deleting an asset is a soft delete by setting status='deleted'; list endpoints must exclude deleted assets.