# Elementor MCP Server — local MCP environment

This backend powers an MCP server that manages WordPress pages built with Elementor, including reading/updating page content and Elementor meta (e.g., _elementor_data) and supporting file-based import/export workflows. It also tracks per-request operations (downloads/updates/deletes) for auditability, error reporting, and to make file-based actions reproducible.

Repository: https://github.com/aguaitech/Elementor-MCP
Homepage: https://smithery.ai/server/@aguaitech/Elementor-MCP

## Datastore

- `wp_sites.json` — Registered WordPress sites that this MCP server can access (base URL + auth). Used as the target for all page operations. (12 rows; fields: ['id', 'name', 'base_url', 'wp_rest_base', 'auth_type', 'auth_username', 'auth_secret_ref', 'default_language', 'status', 'last_health_check_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(base_url)
  - constraint: base_url must be a valid absolute URL
  - constraint: if auth_type != 'none' then auth_secret_ref is required
  - constraint: if auth_type in ('application_password','jwt_bearer') then auth_username is required
- `wp_pages.json` — Locally cached representation of WordPress pages and key Elementor meta needed for read/modify operations. (35 rows; fields: ['id', 'site_id', 'wp_page_id', 'slug', 'title', 'wp_status', 'link', 'elementor_data_json', 'elementor_edit_mode', 'elementor_template_type', 'raw_meta', 'cache_state', 'last_synced_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `cache_state`: ['fresh', 'stale', 'unknown']
  - constraint: unique(site_id, wp_page_id)
  - constraint: unique(site_id, slug) where deleted_at is null
  - constraint: wp_page_id > 0
  - constraint: slug length between 1 and 200
- `page_files.json` — Server-side file artifacts created/used by download_page_to_file and update_page_from_file (stores metadata and content pointer). (34 rows; fields: ['id', 'site_id', 'page_id', 'wp_page_id', 'kind', 'storage_backend', 'storage_path', 'sha256', 'size_bytes', 'format', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['writing', 'ready', 'consumed', 'deleted', 'error']
  - constraint: if page_id is null then wp_page_id is required
  - constraint: wp_page_id is null or wp_page_id > 0
  - constraint: size_bytes is null or size_bytes >= 0
  - constraint: storage_path is non-empty
- `page_operations.json` — Audit log of tool executions (create/get/download/update/delete/slug lookup), including remote request/response summaries and success boolean where applicable. (37 rows; fields: ['id', 'site_id', 'tool_name', 'page_id', 'wp_page_id', 'slug', 'input_file_id', 'output_file_id', 'request_payload', 'response_payload', 'http_status', 'success', 'status', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: wp_page_id is null or wp_page_id > 0
  - constraint: if tool_name='get_page_id_by_slug' then slug is required
- `api_keys.json` — API keys used to authenticate clients of the MCP server and enforce per-key quotas on operations. (21 rows; fields: ['id', 'key_prefix', 'key_hash', 'label', 'status', 'allowed_site_ids', 'rate_limit_per_minute', 'daily_quota_ops', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_prefix)
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
  - constraint: daily_quota_ops >= 1 and daily_quota_ops <= 1000000

## Business rules enforced by the tools

- Every tool execution MUST create a page_operations row with tool_name set to the tool invoked; status transitions must follow the declared lifecycle.
- All WordPress REST calls MUST be associated with exactly one wp_sites row; if the client does not specify a site, the server MUST use a single configured default site_id.
- get_page_id_by_slug: given (site_id, slug), the server MUST query WordPress for the page ID; on success it SHOULD upsert wp_pages with (site_id, wp_page_id, slug) and set cache_state to 'fresh' and last_synced_at.
- get_page: given (site_id, wp_page_id), the server MUST fetch the page and meta including _elementor_data; it MUST upsert wp_pages(site_id, wp_page_id) with elementor_data_json/raw_meta and set cache_state='fresh'.
- download_page_to_file: on success, the server MUST create a page_files row (status transitions writing->ready) and link it from page_operations.output_file_id; the file MUST contain at least _elementor_data and identifiers (wp_page_id, slug).
- update_page: given (site_id, wp_page_id, elementor payload), the server MUST send an update to WordPress; it MUST record page_operations.success=true/false accordingly, and on success mark wp_pages.cache_state='fresh' with updated elementor_data_json if returned/known.
- update_page_from_file: the server MUST read the referenced page_files content (status must be 'ready'), validate it is JSON, extract wp_page_id and Elementor fields, then perform update_page semantics; on success it MUST mark the input file status to 'consumed'.
- delete_page: on success, the server MUST mark wp_pages.deleted_at=now() (soft delete) and set cache_state='unknown' or wp_status='trash' depending on WP response; page_operations.success MUST reflect remote outcome.
- Quota enforcement: for each api_keys.id, the server MUST reject requests when rate_limit_per_minute or daily_quota_ops would be exceeded; rejected requests MUST still create a page_operations row with status='failed' and an error_message indicating quota exceeded.
- FK integrity: page_operations.input_file_id/output_file_id, if present, MUST reference page_files.id; page_files.page_id, if present, MUST reference wp_pages.id; cross-site linking is forbidden (site_id must match across linked rows).