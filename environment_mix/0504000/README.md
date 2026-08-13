# Flux ImageGen Server — local MCP environment

This backend stores image generation requests submitted via an API/MCP server, the available generation models, and the resulting artifacts (URLs and/or stored files with base64 payload metadata). Primary workflows are: (1) list available models, (2) create a generation job from a prompt and options, (3) complete the job with a hosted URL and/or stored file output, tracking safety/enhancement settings and reproducibility seed.

Repository: https://github.com/falahgs/flux-imagegen-mcp-server
Homepage: https://smithery.ai/server/@falahgs/flux-imagegen-mcp-server

## Datastore

- `image_models.json` — Catalog of supported image generation models and their capabilities/constraints. Used by listImageModels and to validate generateImage/generateImageUrl inputs. (12 rows; fields: ['id', 'key', 'display_name', 'provider', 'is_active', 'supports_url_output', 'supports_base64_output', 'supports_safe_filter', 'supports_prompt_enhance', 'min_width', 'max_width', 'min_height', 'max_height', 'default_width', 'default_height', 'created_at', 'updated_at'])
  - lifecycle `is_active`: ['true', 'false']
  - constraint: unique(key)
  - constraint: min_width >= 1
  - constraint: min_height >= 1
  - constraint: max_width >= min_width
- `api_keys.json` — API keys for authenticating and rate-limiting generation requests. Even if the MCP server is used locally, a production service typically tracks keys for abuse prevention and quotas. (30 rows; fields: ['id', 'key_hash', 'name', 'status', 'requests_per_minute_limit', 'daily_image_limit', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit between 1 and 6000
  - constraint: daily_image_limit between 0 and 1000000
- `image_generations.json` — Core table representing a single image generation request derived from generateImageUrl or generateImage. Stores normalized parameters, prompt enhancement decisions, safety filtering choice, and links to produced artifacts. (33 rows; fields: ['id', 'api_key_id', 'tool', 'prompt', 'enhance', 'enhanced_prompt', 'safe', 'model_id', 'seed', 'width', 'height', 'status', 'error_code', 'error_message', 'requested_at', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: prompt length between 1 and 20000
  - constraint: width >= 64 and height >= 64
  - constraint: width % 8 = 0 and height % 8 = 0
  - constraint: seed is null OR (seed >= 0 and seed <= 9007199254740991)
- `image_artifacts.json` — Outputs produced by a generation: hosted URL, base64 payload metadata, and/or a saved file path. A single generation can produce multiple artifacts (e.g., both URL and a stored file). (35 rows; fields: ['id', 'generation_id', 'kind', 'status', 'url', 'mime_type', 'format', 'byte_size', 'sha256', 'base64_data', 'output_path', 'file_name', 'file_extension', 'absolute_file_path', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'available', 'expired', 'deleted']
  - constraint: foreign key (generation_id) references image_generations(id) on delete cascade
  - constraint: kind='url' implies url is not null
  - constraint: kind='base64' implies base64_data is not null
  - constraint: kind='file' implies absolute_file_path is not null
- `usage_events.json` — Append-only ledger for request counting, rate limiting, and cost/latency analytics. Populated on every tool invocation and on completion. (35 rows; fields: ['id', 'api_key_id', 'generation_id', 'tool', 'event_type', 'http_status', 'latency_ms', 'billable_units', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['request_received', 'request_rejected', 'generation_started', 'generation_succeeded', 'generation_failed']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: foreign key (generation_id) references image_generations(id)
  - constraint: latency_ms is null OR latency_ms >= 0
  - constraint: http_status is null OR (http_status between 100 and 599)

## Business rules enforced by the tools

- listImageModels returns rows from image_models where is_active=true, ordered by key; no request parameters are required.
- generateImageUrl and generateImage MUST create an image_generations row with tool set appropriately, status initially 'queued', and requested_at set to now.
- If model is omitted in the tool request, the system uses image_models.key='flux' (must exist and be active); otherwise the provided model must map to an active image_models row.
- If width/height are omitted, defaults are taken from the selected image_models.default_width/default_height; otherwise requested width/height must be within the model min/max and be multiples of 8.
- If enhance is omitted, it defaults to true at the API layer; if enhance=true and prompt enhancement succeeds, image_generations.enhanced_prompt is stored and used for the upstream request; if enhancement fails, the system may proceed with the original prompt but MUST record enhance=true and leave enhanced_prompt null.
- If safe is omitted, it defaults to false at the API layer; if safe=true but the selected model does not support safety filtering, the request MUST be rejected with status failed and error_code='SAFETY_UNSUPPORTED' (or coerced safe=false only if explicitly allowed by product policy; backend should choose one behavior and enforce it consistently).
- Seed is optional; if omitted the system generates a random integer seed and persists it back to image_generations.seed before marking status 'running' to enable reproducibility of stored results.
- On successful completion, image_generations.status transitions to 'succeeded' and completed_at is set; on failure, status transitions to 'failed' and error_code is populated.
- generateImageUrl MUST create or upsert an image_artifacts row with kind='url' and a non-null url, status='available'.
- generateImage MUST create an image_artifacts row with kind='base64' containing base64_data (unless the system streams/omits storage by policy) and SHOULD create a kind='file' artifact with output_path/file_name/format/absolute_file_path when saving to disk is enabled by configuration.
- For generateImage, if outputPath is omitted it defaults to './mcpollinations-output'; if fileName is omitted it is derived from the prompt and stored in image_artifacts.file_name; if format is omitted it defaults to 'png'.
- format accepts only png, jpeg, jpg, webp; mime_type must match the chosen format when present.
- Rate limiting: for authenticated requests, the system MUST reject requests exceeding api_keys.requests_per_minute_limit and/or api_keys.daily_image_limit; rejections are recorded in usage_events with event_type='request_rejected'.
- Every tool invocation writes a usage_events row with event_type='request_received'; generation state changes (started/succeeded/failed) append additional usage_events rows linked to generation_id.