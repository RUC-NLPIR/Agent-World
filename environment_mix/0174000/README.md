# Doc Scraper — local MCP environment

Doc Scraper stores scrape jobs requested via API, tracks their execution lifecycle, and persists the resulting markdown artifacts. The primary workflow is: create a scrape job for a URL with an intended output path, run the scrape, store markdown output (and optional metadata/errors), and allow repeated/updated runs while enforcing deduplication and safety constraints on output paths.

Repository: https://github.com/askjohngeorge/mcp-doc-scraper
Homepage: https://smithery.ai/server/@askjohngeorge/mcp-doc-scraper

## Datastore

- `workspaces.json` — Tenant container for API usage and job isolation. Even if the tool surface is minimal, a real hosted service typically partitions jobs by workspace for quota and security boundaries. (12 rows; fields: ['id', 'name', 'status', 'plan', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: name length between 1 and 120
- `api_keys.json` — API keys used to authenticate scrape requests and attribute usage to a workspace. (17 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'prefix', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(prefix)
  - constraint: key_hash length >= 32
  - constraint: prefix length between 8 and 32
- `scrape_jobs.json` — A single request to scrape documentation from a URL and save it as markdown. This collection directly backs the scrape_docs tool call; tool parameters map to url and requested_output_path. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'url', 'requested_output_path', 'normalized_url', 'url_host', 'url_scheme', 'status', 'attempt', 'error_code', 'error_message', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: url length between 1 and 2048
  - constraint: requested_output_path length between 1 and 4096
  - constraint: attempt >= 0
  - constraint: duration_ms is null or duration_ms >= 0
- `markdown_artifacts.json` — The produced markdown output (and metadata) for a scrape job. Represents what was 'saved as markdown' and allows retrieval, storage tracking, and dedupe by content hash. (18 rows; fields: ['id', 'workspace_id', 'job_id', 'output_path', 'storage_backend', 'storage_uri', 'content_sha256', 'content_bytes', 'markdown_title', 'source_content_type', 'http_status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `storage_backend`: ['local_fs', 's3', 'gcs', 'db_blob']
  - constraint: unique(job_id) -- one final markdown artifact per successful job
  - constraint: unique(workspace_id, output_path, created_at::date) -- avoid multiple writes to same path in a short window unless versioning is implemented
  - constraint: content_bytes >= 0
  - constraint: content_sha256 length = 64

## Business rules enforced by the tools

- scrape_docs(url, output_path) MUST create a scrape_jobs row with url = input url and requested_output_path = input output_path, and set status = 'queued' (or 'running' if executed synchronously).
- A scrape_jobs.url MUST be a valid absolute URL with scheme http or https; other schemes MUST be rejected.
- requested_output_path MUST be validated to prevent directory traversal and absolute-path escapes (e.g., reject '..', null bytes, or paths outside an allowed workspace sandbox).
- A workspace in status 'suspended' or 'deleted' MUST NOT be allowed to create new scrape_jobs.
- When a job transitions to 'running', started_at MUST be set; when it transitions to 'succeeded'/'failed'/'cancelled', finished_at MUST be set and duration_ms MUST be computed as finished_at-started_at (ms) when both exist.
- A job in 'succeeded' MUST have exactly one markdown_artifacts row; a job in 'failed' or 'cancelled' MUST NOT have a markdown_artifacts row.
- On successful scrape, markdown_artifacts.output_path SHOULD equal scrape_jobs.requested_output_path unless a deterministic normalization/sandboxing step is applied; the resolved value MUST be stored in markdown_artifacts.output_path.
- content_sha256 MUST match the stored markdown bytes at storage_uri; integrity verification MUST occur at write time.
- Retries: only jobs in status 'failed' may transition back to 'queued', and attempt MUST increment by 1 on each retry.
- Uniqueness/deduplication: within a workspace, repeated submissions for the same normalized_url and requested_output_path within the service's dedupe window SHOULD return or reuse an existing queued/running job rather than creating unbounded duplicates.