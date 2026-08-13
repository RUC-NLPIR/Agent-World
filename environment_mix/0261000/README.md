# Pinterest MCP Server — local MCP environment

This backend stores Pinterest scraping/search runs initiated via the MCP tools, along with normalized pin/image metadata and optional download artifacts. Main workflows are: create a search run for a keyword (optionally headless), persist the returned image results, fetch detailed info for a specific image URL, and optionally queue/download the found images while enforcing limits and basic deduplication.

Repository: https://github.com/terryso/mcp-pinterest
Homepage: https://smithery.ai/server/@terryso/mcp-pinterest

## Datastore

- `api_keys.json` — API keys used to authenticate callers to the MCP server and apply per-key quotas/rate limits. (17 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'daily_search_limit', 'daily_download_limit', 'daily_getinfo_limit', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: daily_search_limit >= 0
  - constraint: daily_download_limit >= 0
- `search_runs.json` — Represents a single pinterest_search or pinterest_search_and_download invocation, including parameters, execution status, and summary metrics. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'keyword', 'limit', 'headless', 'status', 'error_message', 'started_at', 'finished_at', 'result_count', 'download_requested', 'download_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: limit >= 1
  - constraint: limit <= 100
  - constraint: result_count >= 0
  - constraint: download_count >= 0
- `images.json` — Normalized Pinterest image/pin metadata indexed by canonical image URL; populated from search results and enriched via pinterest_get_image_info. (18 rows; fields: ['id', 'canonical_image_url', 'source_page_url', 'pin_id', 'title', 'description_text', 'pinner_username', 'board_name', 'width', 'height', 'mime_type', 'dominant_color', 'info_status', 'last_info_fetched_at', 'last_info_error', 'created_at', 'updated_at'])
  - lifecycle `info_status`: ['unfetched', 'fetched', 'stale', 'failed']
  - constraint: unique(canonical_image_url)
  - constraint: width is null or width > 0
  - constraint: height is null or height > 0
- `search_results.json` — Join table linking search runs to the images returned, preserving rank/order and any run-specific URLs found during scraping. (17 rows; fields: ['id', 'search_run_id', 'image_id', 'rank', 'found_image_url', 'found_page_url', 'created_at', 'updated_at'])
  - constraint: unique(search_run_id, rank)
  - constraint: unique(search_run_id, image_id)
  - constraint: rank >= 1
  - constraint: rank <= 100
- `downloads.json` — Download jobs/artifacts for images downloaded as part of pinterest_search_and_download runs. (18 rows; fields: ['id', 'search_run_id', 'image_id', 'status', 'attempt_count', 'http_status', 'content_type', 'byte_size', 'sha256', 'storage_backend', 'storage_path', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'downloading', 'succeeded', 'failed', 'skipped']
  - constraint: unique(search_run_id, image_id)
  - constraint: attempt_count >= 0
  - constraint: byte_size is null or byte_size >= 0
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)

## Business rules enforced by the tools

- pinterest_search must create a search_runs row with tool_name='pinterest_search', download_requested=false, status progressing queued->running->(succeeded|failed|cancelled).
- pinterest_search_and_download must create a search_runs row with tool_name='pinterest_search_and_download', download_requested=true, and enqueue downloads rows (status='queued') for up to limit results.
- For both search tools, keyword is required and must be a non-empty trimmed string; limit defaults to 10 and must be between 1 and 100 inclusive; headless defaults to true.
- Each image returned by a run must be upserted into images by canonical_image_url, then linked via search_results with a unique (search_run_id, rank) ordering starting at 1.
- pinterest_get_image_info must upsert/select images by canonical_image_url matching the provided image_url; it must update info_status to fetched on success and set last_info_fetched_at; on failure it must set info_status=failed and last_info_error.
- An API key in status disabled or revoked must not be allowed to create new search_runs or update images via get_image_info.
- Daily quotas must be enforced per api_key_id: number of search_runs created per UTC day must be <= daily_search_limit; number of downloads with status succeeded per UTC day must be <= daily_download_limit; number of successful get_image_info enrichments per UTC day must be <= daily_getinfo_limit.
- A download row may only be created for a search_run where download_requested=true; otherwise the request is rejected.
- When a download succeeds, sha256 should be computed and byte_size/content_type recorded; storage_path must be set and immutable after success.
- FK integrity must be enforced: deleting an api_key is disallowed if it has search_runs; deleting a search_run is disallowed if it has search_results or downloads; deleting an image is disallowed if referenced by search_results or downloads.