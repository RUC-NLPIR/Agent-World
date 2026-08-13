# Wallhaven Wallpaper Search Server — local MCP environment

This backend powers a thin API wrapper over Wallhaven that supports searching wallpapers, fetching wallpaper and tag details, and browsing user collections. It stores cached representations of wallpapers/tags/users/collections and logs each API query (searches, lookups, collection listings) for observability, pagination, and rate-limit enforcement tied to an API key.

Repository: https://github.com/devfurkank/Wallhaven-mcp
Homepage: https://smithery.ai/server/@devfurkank/wallhaven-mcp

## Datastore

- `api_keys.json` — Client credentials used to authenticate requests (for endpoints that require an API key) and to enforce rate limits/quotas. Also links requests to an acting user when applicable. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'owner_user_id', 'rate_limit_per_minute', 'daily_quota', 'requests_today', 'requests_today_reset_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute >= 1 AND rate_limit_per_minute <= 6000
  - constraint: daily_quota >= 1 AND daily_quota <= 1000000
  - constraint: requests_today >= 0 AND requests_today <= daily_quota
- `users.json` — Wallhaven user identities mirrored/cached locally to support user settings and collection browsing. May be linked to an API key for authenticated calls. (30 rows; fields: ['id', 'username', 'status', 'settings', 'settings_etag', 'settings_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(username)
  - constraint: username length between 1 and 64
  - constraint: FKs referencing users must enforce integrity
- `wallpapers.json` — Cached wallpaper objects returned by search and get_wallpaper. Stores core metadata, dimensions, and tag IDs for tag lookup. (36 rows; fields: ['id', 'status', 'source_url', 'page_url', 'file_url', 'thumb_url', 'category', 'purity', 'resolution', 'width', 'height', 'ratio', 'colors', 'views', 'favorites', 'tags', 'raw_payload', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'blocked']
  - constraint: id matches regex ^[0-9a-z]{6}$
  - constraint: width IS NULL OR width >= 1
  - constraint: height IS NULL OR height >= 1
  - constraint: views IS NULL OR views >= 0
- `tags.json` — Tag catalog cached from upstream to serve get_tag_info and to enrich wallpapers. Tag IDs are upstream integers. (30 rows; fields: ['id', 'name', 'alias', 'category', 'purity', 'created_by_username', 'raw_payload', 'status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: id >= 1
  - constraint: unique(name) WHERE name IS NOT NULL
- `collections.json` — User collections mirrored from upstream. Supports listing collections for a username or for the authenticated user, and paging through wallpapers in a collection. (32 rows; fields: ['id', 'owner_user_id', 'upstream_collection_id', 'label', 'description', 'visibility', 'wallpaper_ids', 'status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: FK owner_user_id -> users.id ON DELETE CASCADE
  - constraint: upstream_collection_id >= 1
  - constraint: unique(owner_user_id, upstream_collection_id)
- `requests.json` — Request/response log for all tool invocations. Stores tool parameters for reproducibility, links to cached entities when relevant, and supports quota enforcement and debugging. (38 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'started_at', 'completed_at', 'http_status', 'error_code', 'error_message', 'params', 'result_wallpaper_id', 'result_tag_id', 'result_user_id', 'result_collection_id', 'result_count', 'upstream_cache_hit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'fulfilled', 'failed']
  - constraint: FK api_key_id -> api_keys.id ON DELETE SET NULL
  - constraint: FK result_wallpaper_id -> wallpapers.id ON DELETE SET NULL
  - constraint: FK result_tag_id -> tags.id ON DELETE SET NULL
  - constraint: FK result_user_id -> users.id ON DELETE SET NULL

## Business rules enforced by the tools

- search_wallpapers must validate sorting in {date_added,relevance,random,views,favorites,toplist} and order in {asc,desc}; otherwise reject the request as failed with http_status=400 and do not call upstream.
- search_wallpapers.page and get_collection_wallpapers.page must be integers >= 1; otherwise reject with http_status=400.
- get_wallpaper must accept wallpaper_id matching ^[0-9a-z]{6}$; otherwise reject with http_status=400.
- get_tag_info must accept tag_id >= 1; otherwise reject with http_status=400.
- get_user_settings requires an api_key_id referencing an api_keys row with status=active; otherwise return http_status=401 and log the request as failed.
- get_collections with username omitted requires an active api_key_id and api_keys.owner_user_id must be non-null; otherwise return http_status=401/403 and log as failed.
- get_collection_wallpapers must resolve (username, collection_id) to exactly one collections row by joining users.username to users.id and collections.upstream_collection_id; if not found return http_status=404.
- For any authenticated request, the system must enforce api_keys.daily_quota and rate_limit_per_minute; exceeding either returns http_status=429 and must not mutate cached entities.
- When a request is fulfilled, requests.status must transition from received -> fulfilled and completed_at must be set; when failed, received -> failed and error_code/error_message must be populated.
- Wallpaper/tag/user/collection cache refresh should update fetched_at and raw_payload and set updated_at; it must not change primary identifiers (wallpapers.id, tags.id, users.username uniqueness, collections(owner_user_id, upstream_collection_id) uniqueness).