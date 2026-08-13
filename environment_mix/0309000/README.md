# fal.ai Model Server — local MCP environment

This backend powers a thin model-server wrapper over fal.ai: it indexes available models, retrieves each model's OpenAPI schema, submits generation requests (sync or queued), and tracks their lifecycle until completion/cancellation. It also supports uploading user files into fal.ai-backed storage and returning stable file URLs for use in generation inputs.

Repository: https://github.com/antonioevans/mcp-fal
Homepage: https://smithery.ai/server/@antonioevans/mcp-fal

## Datastore

- `api_keys.json` — API keys used by clients to authenticate to the model server and apply per-key quotas. Keys are scoped to a project/workspace and used to attribute searches, uploads, schema fetches, and generation jobs. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'project_id', 'name', 'status', 'quota_requests_per_minute', 'quota_concurrent_generations', 'quota_upload_bytes_per_day', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(project_id, name)
  - constraint: quota_requests_per_minute between 1 and 6000
  - constraint: quota_concurrent_generations between 1 and 500
- `projects.json` — Top-level tenant/workspace for isolation of API keys, jobs, and uploads. (12 rows; fields: ['id', 'name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: name length between 1 and 128
- `models.json` — Catalog of fal.ai models known to the server. Used for listing/searching and as the authoritative reference for generation requests and schema retrieval. (35 rows; fields: ['id', 'model_id', 'display_name', 'description', 'provider', 'tags', 'status', 'openapi_schema_json', 'schema_etag', 'schema_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(model_id)
  - constraint: display_name length between 1 and 256
  - constraint: tags array length between 0 and 64
- `generation_requests.json` — User-submitted generation calls to fal.ai models, including queued request URLs and lifecycle tracking. Supports checking status/result and cancelling queued requests. (35 rows; fields: ['id', 'project_id', 'api_key_id', 'model_id', 'model_identifier', 'input_json', 'mode', 'status', 'upstream_request_id', 'response_url', 'status_url', 'cancel_url', 'result_json', 'error_json', 'started_at', 'finished_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired']
  - constraint: mode in ('sync','queued')
  - constraint: if mode='queued' then (response_url is not null and status_url is not null and cancel_url is not null)
  - constraint: if mode='sync' then (response_url is null and status_url is null and cancel_url is null)
  - constraint: unique(response_url) where response_url is not null
- `uploads.json` — Files uploaded to fal.ai storage through the server. Records returned file_url and metadata so generation inputs can reference them. (26 rows; fields: ['id', 'project_id', 'api_key_id', 'local_path', 'original_filename', 'content_type', 'size_bytes', 'file_url', 'storage_provider', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['uploading', 'available', 'failed', 'deleted']
  - constraint: unique(file_url) where file_url is not null
  - constraint: local_path like '/%'
  - constraint: size_bytes is null or size_bytes >= 0

## Business rules enforced by the tools

- Tool `models` returns models where models.status in ('active','deprecated') ordered by display_name; disabled models are excluded by default.
- Tool `search` performs a case-insensitive search over models.model_id, models.display_name, models.description, and models.tags; returns only models with status != 'disabled'.
- Tool `schema` accepts an external model id string (e.g. 'fal-ai/flux/dev') and must resolve it to models.model_id; if not found, it creates a models row with status='active' (or 'disabled' if upstream says unavailable) and then fetches/caches openapi_schema_json and schema_fetched_at.
- Tool `generate` must create a generation_requests row with input_json capturing the full request payload; model_identifier must equal models.model_id at submission time.
- If fal.ai responds with queued URLs, generation_requests.mode must be 'queued' and status must start at 'queued'; response_url/status_url/cancel_url must be persisted and each must be globally unique.
- Tool `status` must locate generation_requests by matching the provided url to generation_requests.status_url; if no match exists, the server may create a stub generation_requests row only if the url can be validated as belonging to the configured fal.ai domain; otherwise return not-found.
- Tool `result` must locate generation_requests by response_url; on successful upstream retrieval, it must set status='succeeded' and persist result_json and finished_at; on upstream terminal error, set status='failed' and persist error_json and finished_at.
- Tool `cancel` must locate generation_requests by cancel_url; it may only transition status from 'queued' or 'running' to 'cancelled' when upstream confirms cancellation; cancellation attempts against terminal states must be idempotent and return the existing terminal state.
- Tool `upload` must create uploads row with status='uploading' then set status='available' and file_url on success or status='failed' with error_message on failure; file_url must be unique.
- For any request authenticated by an API key, api_keys.status must be 'active' and the owning projects.status must be 'active'; otherwise operations are rejected.
- Rate limiting/quota enforcement: within a rolling 60s window per api_key_id, total calls to (models, search, schema, generate, status, result, cancel, upload) must be <= api_keys.quota_requests_per_minute.
- Concurrency enforcement: count of generation_requests for an api_key_id with status in ('queued','running') must be <= api_keys.quota_concurrent_generations at time of `generate`.
- Daily upload cap: sum of uploads.size_bytes for an api_key_id where created_at is within the same UTC day and status='available' must be <= api_keys.quota_upload_bytes_per_day.