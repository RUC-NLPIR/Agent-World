# text2image — local MCP environment

This backend stores text-to-image generation requests, the resulting generated images, and the API clients that create them. The main workflow is: an API client submits an image_generation request (prompt + width/height), a generation job is created and processed, and one or more image assets are stored and returned as URLs.

Repository: https://github.com/PawNzZi/image-server
Homepage: https://smithery.ai/server/@PawNzZi/image-server

## Datastore

- `api_clients.json` — Represents authenticated callers (apps/users) issuing image generation requests, used for quota/rate limiting and auditing. (12 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'quota_requests_per_day', 'quota_pixels_per_day', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: quota_requests_per_day >= 0
  - constraint: quota_pixels_per_day >= 0
- `generation_requests.json` — A single invocation of the image_generation tool: stores prompt and requested dimensions, status, and links to produced images. (19 rows; fields: ['id', 'client_id', 'image_prompt', 'width', 'height', 'prompt_language', 'expanded_prompt_en', 'status', 'error_code', 'error_message', 'source_ip', 'idempotency_key', 'requested_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
  - constraint: width in [64, 4096]
  - constraint: height in [64, 4096]
  - constraint: width % 8 = 0 AND height % 8 = 0
- `image_assets.json` — Stores metadata for generated image files and the URLs returned to callers. (19 rows; fields: ['id', 'request_id', 'status', 'storage_provider', 'storage_path', 'public_url', 'content_type', 'byte_size', 'width', 'height', 'sha256', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'available', 'deleted']
  - constraint: foreign key (request_id) references generation_requests(id) on delete cascade
  - constraint: unique(public_url)
  - constraint: byte_size >= 0
  - constraint: width in [64, 4096]
- `usage_daily.json` — Aggregated per-client daily usage for enforcing request and pixel quotas efficiently. (12 rows; fields: ['id', 'client_id', 'usage_date', 'requests_count', 'pixels_count', 'created_at', 'updated_at'])
  - constraint: foreign key (client_id) references api_clients(id) on delete cascade
  - constraint: unique(client_id, usage_date)
  - constraint: requests_count >= 0
  - constraint: pixels_count >= 0

## Business rules enforced by the tools

- image_generation(image_prompt, width, height) must create exactly one generation_requests row with image_prompt mapped from the tool parameter, and width/height defaulting to 1024 when omitted.
- generation_requests.width and generation_requests.height must satisfy width,height in [64,4096] and be divisible by 8; otherwise the request is rejected before persisting or persisted as failed with error_code='invalid_dimensions' (implementation choice must be consistent).
- On accepting a request, the system must enforce api_clients.status='active'; otherwise reject with an authorization error.
- Before accepting a request, usage_daily for (client_id, today_utc) must not exceed api_clients.quota_requests_per_day and api_clients.quota_pixels_per_day after adding (1 request, width*height pixels); otherwise reject with error_code='quota_exceeded'.
- If generation_requests.idempotency_key is provided, repeated calls from the same client with the same idempotency_key must return the existing request result (and must not increment usage_daily again).
- A request may transition statuses only according to the declared lifecycle transitions; in particular, once succeeded/failed/cancelled it is terminal.
- When a request reaches status='succeeded', at least one image_assets row must exist for that request with status='available' and public_url non-null; the URL returned by the tool must be image_assets.public_url.
- image_assets rows may only be created for generation_requests in status in ('running','succeeded'); creating assets for queued/failed/cancelled requests is invalid.
- Deleting an api_client (status='deleted') must not physically remove generation_requests; it must prevent new requests while retaining historical data (FK on generation_requests is restrict).
- public_url must be unique across image_assets and must be a valid absolute URL string (validated at application layer).