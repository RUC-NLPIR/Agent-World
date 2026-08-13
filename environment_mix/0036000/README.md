# Jimeng AI Image Generation Server — local MCP environment

This backend supports a small Jimeng-based image generation API service. It stores API clients, image generation jobs, and resulting image artifacts so the service can accept requests, track lifecycle/status, and return outputs for the generateImage tool while hello serves as a health/metadata endpoint.

Repository: https://github.com/Hans-M-Yin/jimeng-mcp
Homepage: https://smithery.ai/server/@Hans-M-Yin/jimeng-mcp

## Datastore

- `api_clients.json` — Represents calling clients (tenants) and their authentication/quota configuration for accessing the image generation API. (12 rows; fields: ['id', 'name', 'status', 'default_model', 'rate_limit_rpm', 'monthly_job_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: rate_limit_rpm >= 1 and rate_limit_rpm <= 6000
  - constraint: monthly_job_quota >= 0 and monthly_job_quota <= 100000
- `api_keys.json` — API keys used to authenticate requests. A key maps to an API client and can be revoked/rotated. (20 rows; fields: ['id', 'client_id', 'key_hash', 'key_prefix', 'status', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: foreign key(client_id) references api_clients(id) on delete restrict
  - constraint: unique(key_hash)
  - constraint: unique(client_id, key_prefix)
- `image_generation_jobs.json` — A single image generation request/job. Because the tool surface omits parameters, the request payload is stored as an opaque JSON object for forwards compatibility and debugging. (34 rows; fields: ['id', 'client_id', 'api_key_id', 'status', 'request_payload', 'model', 'seed', 'error_code', 'error_message', 'queued_at', 'started_at', 'finished_at', 'compute_time_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(client_id) references api_clients(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: compute_time_ms is null or compute_time_ms >= 0
  - constraint: seed is null or (seed >= 0 and seed <= 2147483647)
- `generated_images.json` — Output artifacts produced by an image generation job. A job may produce one or multiple images, each stored as a separate row with storage metadata. (36 rows; fields: ['id', 'job_id', 'index', 'status', 'storage_provider', 'storage_bucket', 'storage_key', 'content_type', 'byte_size', 'width', 'height', 'sha256', 'public_url', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted']
  - constraint: foreign key(job_id) references image_generation_jobs(id) on delete cascade
  - constraint: unique(job_id, index)
  - constraint: index >= 0 and index <= 63
  - constraint: byte_size >= 1 and byte_size <= 104857600
- `request_audit_log.json` — Immutable log of inbound tool invocations (hello, generateImage) for observability, abuse detection, and debugging. (38 rows; fields: ['id', 'client_id', 'api_key_id', 'tool_name', 'request_payload', 'response_status_code', 'latency_ms', 'job_id', 'ip_address', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['hello', 'generateImage']
  - constraint: foreign key(client_id) references api_clients(id) on delete set null
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: foreign key(job_id) references image_generation_jobs(id) on delete set null
  - constraint: response_status_code >= 100 and response_status_code <= 599

## Business rules enforced by the tools

- hello must create a request_audit_log row with tool_name='hello' and an empty object request_payload if none is provided; it must not create image_generation_jobs.
- generateImage must create a request_audit_log row with tool_name='generateImage' and then create an image_generation_jobs row with request_payload equal to the received arguments (empty object allowed).
- A generateImage call authenticated with an api_key must resolve to exactly one active api_keys row and its api_clients row must be status='active'; otherwise the request is rejected and only request_audit_log is written (no job row).
- Rate limiting is enforced per api_client using rate_limit_rpm; requests exceeding the limit are rejected with response_status_code=429 and no job is created.
- Monthly quota is enforced per api_client using monthly_job_quota; once exceeded for the current calendar month, generateImage requests are rejected with response_status_code=403 (or 429) and no job is created.
- image_generation_jobs status must follow the declared transitions; once in succeeded/failed/cancelled it is immutable except for updated_at and attaching generated_images.
- generated_images rows may only be created for jobs with status='running' or 'succeeded'; after job status becomes 'failed' or 'cancelled', no new artifacts may be attached.
- For each generated_images row, (job_id, index) must be unique; index starts at 0 and must be contiguous in returned results even if internal storage is eventually consistent.
- Deleting an image_generation_jobs row (administrative cleanup) must cascade-delete generated_images rows, but must not delete request_audit_log rows.
- api_keys.key_hash must be stored as a one-way hash; raw API keys must never be persisted in any collection.