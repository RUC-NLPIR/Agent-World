# DALL-E Image Generator — local MCP environment

This backend stores OpenAI API keys, image generation/edit/variation jobs, and the resulting image assets produced by DALL-E. Main workflows: a client validates a key, then submits a job (generate/edit/variation) which runs against OpenAI and persists outputs as image assets linked to the job for later retrieval and auditing.

Repository: https://github.com/Garoth/dalle-mcp
Homepage: https://smithery.ai/server/@Garoth/dalle-mcp

## Datastore

- `api_keys.json` — Stored OpenAI API keys (or references) used to authenticate requests to OpenAI; includes validation status and basic usage tracking for throttling and auditing. (12 rows; fields: ['id', 'provider', 'key_hash', 'key_ciphertext', 'secret_ref', 'label', 'status', 'last_validated_at', 'last_validation_error', 'requests_total', 'images_total', 'rate_limit_rpm', 'rate_limit_rpd', 'created_at', 'updated_at'])
  - lifecycle `status`: ['unvalidated', 'valid', 'invalid', 'disabled']
  - constraint: unique(provider, key_hash)
  - constraint: exactly_one_non_null(key_ciphertext, secret_ref)
  - constraint: requests_total >= 0
  - constraint: images_total >= 0
- `requests.json` — Inbound tool invocations recorded for audit and debugging, including validate_key and image operations. Serves as the parent log for one or more DALL-E jobs created by the request. (35 rows; fields: ['id', 'tool_name', 'api_key_id', 'idempotency_key', 'client_ip', 'user_agent', 'input_payload', 'status', 'error_code', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: unique(idempotency_key) where idempotency_key is not null
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: tool_name = 'validate_key' implies api_key_id is not null
  - constraint: tool_name in ('generate_image','edit_image','create_variation') implies api_key_id is not null
- `image_jobs.json` — Asynchronous jobs representing generate/edit/variation operations against DALL-E. Each job may produce one or more output image assets. (21 rows; fields: ['id', 'request_id', 'api_key_id', 'job_type', 'status', 'prompt', 'model', 'n', 'size', 'source_image_asset_id', 'mask_image_asset_id', 'upstream_request_id', 'upstream_response', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(request_id) references requests(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: foreign key(source_image_asset_id) references image_assets(id) on delete set null
  - constraint: foreign key(mask_image_asset_id) references image_assets(id) on delete set null
- `image_assets.json` — Stored image inputs/outputs. Outputs are produced by jobs; inputs may be uploaded/imported and later referenced by edit/variation jobs. (35 rows; fields: ['id', 'job_id', 'asset_role', 'status', 'mime_type', 'byte_size', 'width', 'height', 'sha256', 'storage_backend', 'storage_key', 'external_url', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['staged', 'stored', 'deleted']
  - constraint: byte_size >= 0
  - constraint: width is null or width > 0
  - constraint: height is null or height > 0
  - constraint: unique(sha256) where sha256 is not null

## Business rules enforced by the tools

- Tool validate_key must create a requests row with tool_name='validate_key' and must set api_keys.status to 'valid' or 'invalid' (or 'disabled' if administratively blocked) based on an upstream authentication check.
- Tools generate_image, edit_image, and create_variation must create a requests row with the corresponding tool_name and at least one image_jobs row with matching api_key_id and request_id.
- generate_image must create an image_jobs row with job_type='generate'. edit_image must create an image_jobs row with job_type='edit'. create_variation must create an image_jobs row with job_type='variation'.
- For edit and variation jobs, source_image_asset_id must reference an image_assets row with status='stored' and asset_role='input'. For edit jobs, if mask_image_asset_id is provided, it must reference an image_assets row with status='stored' and asset_role='mask'.
- When an image job succeeds, the system must create at least one image_assets row with job_id set to the job id, asset_role='output', and status='stored' (or 'staged' followed by 'stored').
- A request may be marked succeeded only if all image jobs created by it are in status='succeeded'. A request must be marked failed if any created job is in status='failed' and no remaining jobs can succeed.
- Rate limiting: before running a request, the system must ensure api_keys.requests_total and configured rate_limit_rpm/rpd are not exceeded; otherwise create a failed requests row with error_code='rate_limited' and do not create image_jobs.
- Key material handling: plaintext API keys must never be stored; only key_hash plus either key_ciphertext or secret_ref may be persisted.
- Idempotency: if idempotency_key is provided and a requests row already exists with the same idempotency_key, the system must return the existing request outcome and must not create new image_jobs or image_assets.
- Deletion: setting image_assets.status='deleted' must not remove the row; it must prevent the asset from being used as source_image_asset_id or mask_image_asset_id in new jobs.