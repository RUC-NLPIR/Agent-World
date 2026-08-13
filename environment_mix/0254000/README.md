# URL to Image Converter — local MCP environment

This backend powers a URL-to-image conversion service that generates screenshots of web pages via an API. It stores conversion jobs (requests), the resulting image artifacts, and access/usage controls (API keys and per-key quotas) to protect the renderer and enable operational auditing.

Repository: https://github.com/alperenkocyigit/html-to-image-mcp
Homepage: https://smithery.ai/server/@alperenkocyigit/html-to-image-mcp

## Datastore

- `api_keys.json` — API keys used to authenticate and authorize clients of the URL-to-image converter, including quotas and status. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'name', 'status', 'requests_per_minute_limit', 'requests_per_day_limit', 'concurrent_jobs_limit', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: requests_per_minute_limit >= 1 and requests_per_minute_limit <= 6000
  - constraint: requests_per_day_limit >= 1 and requests_per_day_limit <= 1000000
- `screenshot_jobs.json` — A single screenshot conversion request submitted to the system. Even though the public tool surface does not expose parameters, the production backend tracks the resolved target URL and render settings for auditing and reproducibility. (17 rows; fields: ['id', 'api_key_id', 'status', 'target_url', 'final_url', 'render_engine', 'viewport_width', 'viewport_height', 'device_scale_factor', 'full_page', 'wait_until', 'timeout_ms', 'http_status', 'error_code', 'error_message', 'attempt_count', 'started_at', 'finished_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired']
  - constraint: fk(api_key_id) references api_keys.id on delete restrict
  - constraint: viewport_width >= 100 and viewport_width <= 10000
  - constraint: viewport_height >= 100 and viewport_height <= 10000
  - constraint: device_scale_factor >= 0.5 and device_scale_factor <= 4.0
- `image_artifacts.json` — The stored screenshot outputs for a screenshot job (original, thumbnails, alternate formats). (18 rows; fields: ['id', 'job_id', 'status', 'variant', 'format', 'width_px', 'height_px', 'byte_size', 'sha256', 'storage_backend', 'storage_bucket', 'storage_key', 'content_type', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['writing', 'available', 'deleted']
  - constraint: fk(job_id) references screenshot_jobs.id on delete cascade
  - constraint: unique(job_id, variant, format)
  - constraint: width_px >= 1 and width_px <= 20000
  - constraint: height_px >= 1 and height_px <= 20000
- `usage_events.json` — Immutable request accounting and operational logs for quota enforcement and debugging. (17 rows; fields: ['id', 'api_key_id', 'job_id', 'event_type', 'request_id', 'client_ip', 'user_agent', 'cost_units', 'created_at'])
  - constraint: fk(api_key_id) references api_keys.id on delete restrict
  - constraint: fk(job_id) references screenshot_jobs.id on delete set null
  - constraint: cost_units >= 0 and cost_units <= 1000
  - constraint: event_type in ('take_screenshot_called','job_queued','job_started','job_succeeded','job_failed','job_cancelled')

## Business rules enforced by the tools

- take_screenshot must require a valid api_keys record with status='active' (otherwise reject).
- On take_screenshot, the system must write a usage_events row with event_type='take_screenshot_called' and cost_units=1 (or the configured unit cost).
- A take_screenshot call must create exactly one screenshot_jobs row (status='queued') unless rejected for auth/quota.
- Quota enforcement: within any rolling 60-second window, usage_events(cost_units) for the api_key_id must be <= api_keys.requests_per_minute_limit; within a UTC day, <= api_keys.requests_per_day_limit.
- Concurrency enforcement: number of screenshot_jobs for an api_key_id with status in ('queued','running') must be <= api_keys.concurrent_jobs_limit before allowing a new queued job.
- A screenshot_jobs row may only transition according to the declared lifecycle transitions; attempts to skip states (e.g., queued->succeeded) must be rejected.
- A screenshot job marked 'succeeded' must have at least one image_artifacts row with status='available' and variant='original'.
- Deleting/expiring a job must transition artifacts to status='deleted' (soft delete) and set deleted_at; storage objects should be scheduled for cleanup.
- Idempotency: if request_id is provided and an existing usage_events row with the same (api_key_id, request_id, event_type='take_screenshot_called') exists, the service must not create a second screenshot_jobs row and should return the prior job/result.