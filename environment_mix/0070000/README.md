# Fetch — local MCP environment

This backend powers a URL fetching and content-extraction API that retrieves a web resource, optionally returns raw content, and otherwise extracts readable markdown plus discovered image URLs. It stores fetch requests, the retrieved HTTP response metadata/body, and the extracted representation so requests can be audited, paginated (startIndex/maxLength), cached, and rate-limited per API key.

Repository: https://github.com/smithery-ai/mcp-fetch
Homepage: https://smithery.ai/server/@smithery-ai/fetch

## Datastore

- `api_keys.json` — API credentials used to authenticate callers and apply quotas for the fetch tool. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'quota_requests_per_day', 'quota_bytes_per_day', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: quota_requests_per_day >= 0
  - constraint: quota_bytes_per_day >= 0
  - constraint: status = 'revoked' implies revoked_at is not null
- `fetch_requests.json` — Each invocation of the fetch tool, storing parameters (url, maxLength, startIndex, raw), status, and linkage to stored results. (20 rows; fields: ['id', 'api_key_id', 'url', 'url_normalized', 'max_length', 'start_index', 'raw', 'status', 'error_code', 'error_message', 'cache_key', 'cache_hit', 'http_response_id', 'extraction_id', 'requested_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'processing', 'succeeded', 'failed']
  - constraint: max_length > 0 and max_length <= 1000000
  - constraint: start_index >= 0
  - constraint: unique(cache_key) is NOT enforced globally because results can change over time; caching uses http_responses/extractions with freshness rules
  - constraint: status in ('succeeded','failed') implies completed_at is not null
- `http_responses.json` — Captured HTTP response metadata and (optionally) a stored body for a URL fetch. May be referenced by multiple fetch requests to enable caching. (18 rows; fields: ['id', 'cache_key', 'url_final', 'status_code', 'content_type', 'etag', 'last_modified', 'fetched_at', 'headers', 'body_storage', 'body_text', 'body_base64', 'body_object_ref', 'body_bytes', 'created_at', 'updated_at'])
  - lifecycle `body_storage`: ['inline_text', 'inline_base64', 'object_store_ref', 'omitted']
  - constraint: status_code >= 100 and status_code <= 599
  - constraint: body_bytes >= 0
  - constraint: unique(cache_key, fetched_at)
  - constraint: body_storage = 'inline_text' implies body_text is not null and body_base64 is null and body_object_ref is null
- `extractions.json` — Derived content from an HTTP response: extracted markdown, discovered image URLs, and offsets to support pagination by startIndex/maxLength. (18 rows; fields: ['id', 'http_response_id', 'cache_key', 'status', 'markdown', 'markdown_length', 'title', 'language', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'succeeded', 'failed']
  - constraint: markdown_length >= 0
  - constraint: status = 'succeeded' implies markdown is not null
  - constraint: status = 'failed' implies error_code is not null
  - constraint: unique(http_response_id)
- `extraction_images.json` — Child table listing image URLs discovered during extraction, in document order. (17 rows; fields: ['id', 'extraction_id', 'position', 'image_url', 'alt_text', 'created_at', 'updated_at'])
  - lifecycle `position`: []
  - constraint: position >= 0
  - constraint: unique(extraction_id, position)
  - constraint: unique(extraction_id, image_url)

## Business rules enforced by the tools

- A fetch tool call MUST create a fetch_requests row capturing url, max_length (default 20000 if not provided), start_index (default 0), and raw (default false).
- Requests MUST reject maxLength <= 0 or maxLength > 1000000; requests MUST reject startIndex < 0.
- url MUST be a valid absolute URI and must be stored both as provided (url) and in normalized form (url_normalized).
- fetch_requests.status transitions MUST follow the declared lifecycle; terminal states are succeeded and failed.
- If raw=true, the response content returned to the caller MUST be derived from http_responses body fields; if raw=false it MUST be derived from extractions.markdown.
- Pagination MUST be applied after selecting the output string (raw body text/base64-decoded text when raw=true; markdown when raw=false): return substring starting at start_index with length max_length (or until end).
- If start_index is greater than the length of the selected output, the returned content MUST be an empty string and the request may still be marked succeeded.
- When raw=false and extraction is required, the system MUST create or reuse an extractions row tied to the stored http_response and set extractions.status to succeeded before marking the request succeeded.
- Discovered images during extraction MUST be stored in extraction_images with deterministic ordering (position) and absolute resolved URLs.
- If an api_key_id is present, the system MUST enforce api_keys.status='active' and MUST enforce daily quotas: number of fetch_requests.requested_at per day <= quota_requests_per_day and sum of (returned characters or body_bytes) per day <= quota_bytes_per_day (best-effort).
- On any failure (network error, non-2xx treated as error by policy, unsupported content type, extraction failure), fetch_requests.status MUST be failed and error_code MUST be set.