# WordPress Integration Server — local MCP environment

This backend stores WordPress site connections and a synchronized representation of WordPress posts created/updated/read via the integration server. Main workflows are: authenticate to a configured WP site, create/update posts through the WP REST API, and list posts (optionally from cache) while tracking sync and error states.

Repository: https://github.com/Leonelberio/the-wordpress-mcp-server
Homepage: https://smithery.ai/server/@Leonelberio/the-wordpress-mcp-server

## Datastore

- `wp_sites.json` — Registered WordPress site connections the server can operate on, including base URL and auth configuration metadata. (12 rows; fields: ['id', 'name', 'base_url', 'wp_rest_base', 'auth_type', 'auth_username', 'auth_secret_ref', 'status', 'last_healthcheck_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(base_url)
  - constraint: name <> ''
  - constraint: base_url LIKE 'http%'
  - constraint: wp_rest_base LIKE '/%'
- `wp_posts.json` — Locally cached representation of WordPress posts for each connected site. Used to serve get_posts and to track mapping to remote WP post IDs for update_post. (33 rows; fields: ['id', 'site_id', 'wp_post_id', 'wp_post_type', 'slug', 'title', 'content', 'excerpt', 'author_wp_user_id', 'status', 'wp_status', 'wp_link', 'remote_modified_at', 'last_synced_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'scheduled', 'trashed', 'sync_pending', 'sync_error']
  - constraint: fk(site_id) references wp_sites(id) on delete cascade
  - constraint: unique(site_id, wp_post_id)
  - constraint: title <> ''
  - constraint: wp_post_id is null or wp_post_id > 0
- `post_operations.json` — Append-only log of create_post/update_post/get_posts calls and their WP API interactions for auditing, debugging, rate limiting, and retries. (33 rows; fields: ['id', 'site_id', 'post_id', 'operation', 'status', 'request_payload', 'response_payload', 'http_status', 'error', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(site_id) references wp_sites(id) on delete restrict
  - constraint: fk(post_id) references wp_posts(id) on delete set null
  - constraint: operation in ('create_post','update_post','get_posts')
  - constraint: status in ('queued','running','succeeded','failed','cancelled')
- `api_keys.json` — API keys used by clients to call this integration server; used for basic access control and per-key throttling. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'rate_limit_per_minute', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: label <> ''
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
  - constraint: status in ('active','revoked')

## Business rules enforced by the tools

- Every create_post call MUST create a post_operations row with operation='create_post' and status transitions queued->running->(succeeded|failed|cancelled).
- On successful create_post, the system MUST upsert a wp_posts row for the target site and populate wp_post_id, wp_link, wp_status, remote_modified_at, and last_synced_at; wp_posts.status MUST move to one of (draft|published|scheduled) and MUST NOT remain sync_pending.
- Every update_post call MUST reference an existing wp_posts row OR provide a known (site_id, wp_post_id) mapping; if the mapping is missing, the operation MUST fail with status='failed' and an error payload recorded.
- get_posts MUST read from wp_posts for the requested/active site; if a background refresh from WordPress is performed, it MUST be logged as a post_operations row with operation='get_posts'.
- A wp_sites row with status != 'active' MUST NOT be used for outbound WordPress REST calls; attempts MUST be logged in post_operations with status='failed'.
- The pair (site_id, wp_post_id) MUST be unique when wp_post_id is not null to prevent ambiguous updates.
- API requests MUST be authenticated with an api_keys record in status='active'; revoked keys MUST be rejected and MUST NOT create post_operations rows.
- Rate limiting MUST be enforced per api_keys.rate_limit_per_minute; requests exceeding the limit MUST be rejected and SHOULD NOT enqueue queued operations.