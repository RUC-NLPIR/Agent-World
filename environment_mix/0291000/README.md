# Jimeng Image Generation Server — local MCP environment

This backend supports a Jimeng image generation API server, tracking client projects, requests to generate images, and the resulting generated assets. Core workflows: a client/project submits a generation request, the server queues/runs it against a configured Jimeng provider, stores outputs and metadata, and exposes simple health/hello plus generation endpoints.

Repository: https://github.com/c-rick/jimeng-mcp
Homepage: https://smithery.ai/server/@c-rick/jimeng-mcp

## Datastore

- `projects.json` — Represents a client namespace for calling the service and grouping image generation requests (a practical backing entity even if the public tool surface is minimal). (12 rows; fields: ['id', 'name', 'status', 'default_provider_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_provider_id references providers(id) on update restrict on delete set null
- `providers.json` — Configuration records for Jimeng image generation backends (endpoints, model/version hints, and secrets references). (12 rows; fields: ['id', 'provider_type', 'base_url', 'model', 'status', 'secrets_ref', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(provider_type, base_url, model)
  - constraint: base_url != ''
- `generation_requests.json` — A single call to generate an image (the primary entity behind the generateImage tool). Stores input payload (even if empty), execution state, and provider interaction metadata. (18 rows; fields: ['id', 'project_id', 'provider_id', 'status', 'input', 'provider_request_id', 'error_code', 'error_message', 'queued_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: project_id references projects(id) on delete restrict
  - constraint: provider_id references providers(id) on delete set null
  - constraint: status in ('queued','running','succeeded','failed','cancelled')
  - constraint: finished_at is null or started_at is not null
- `generated_images.json` — Outputs produced by a generation request (one-to-many). Stores storage locations and basic file metadata. (17 rows; fields: ['id', 'generation_request_id', 'status', 'storage_backend', 'object_key', 'public_url', 'content_type', 'bytes', 'width', 'height', 'sha256', 'created_at', 'updated_at'])
  - lifecycle `status`: ['stored', 'deleted']
  - constraint: generation_request_id references generation_requests(id) on delete cascade
  - constraint: unique(storage_backend, object_key)
  - constraint: bytes is null or bytes >= 0
  - constraint: width is null or width > 0
- `api_call_logs.json` — Operational logs for tool calls (hello and generateImage), used for auditing, debugging, and basic usage tracking. (18 rows; fields: ['id', 'project_id', 'tool_name', 'request_payload', 'response_status', 'duration_ms', 'generation_request_id', 'client_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['hello', 'generateImage']
  - constraint: project_id references projects(id) on delete set null
  - constraint: generation_request_id references generation_requests(id) on delete set null
  - constraint: response_status between 100 and 599
  - constraint: duration_ms >= 0

## Business rules enforced by the tools

- Calling hello MUST insert an api_call_logs row with tool_name='hello' and request_payload={}.
- Calling generateImage MUST insert an api_call_logs row with tool_name='generateImage' and request_payload={} and MUST create exactly one generation_requests row (input={}) unless the server returns an error before request creation.
- When a generation_requests row is created, status MUST start as 'queued' (or 'running' if executed synchronously) and queued_at MUST be set when status becomes 'queued'.
- A generation_requests row may transition only via the declared lifecycle transitions; once in a terminal state (succeeded/failed/cancelled) it MUST NOT change status again.
- If generation_requests.status='succeeded', then at least one generated_images row MUST exist for that generation_request_id and each generated_images.status MUST be 'stored' at creation time.
- If generation_requests.status IN ('failed','cancelled'), then no new generated_images rows may be created for that generation_request_id after finished_at is set.
- If provider_id is null at generation time, the implementation MUST resolve provider_id from projects.default_provider_id; if still null, the request MUST fail with error_code='NO_PROVIDER_CONFIG'.
- providers.status='disabled' MUST prevent new generation_requests from entering 'running' using that provider.
- projects.status IN ('suspended','deleted') MUST prevent creation of new generation_requests for that project.
- api_call_logs.generation_request_id MUST be non-null only when tool_name='generateImage'.