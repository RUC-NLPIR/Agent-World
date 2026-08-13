# Sherlock MCP Server — local MCP environment

This backend stores username-search requests executed via the Sherlock engine, the per-site results found for each request, and the catalog of supported platforms (including whether a platform is NSFW). Primary workflows are: accept a username search (standard or NSFW-inclusive), run checks across configured platforms, persist the run and results, and return links found.

Repository: https://github.com/qKitNp/sherlock_mcp
Homepage: https://smithery.ai/server/@qKitNp/sherlock_mcp

## Datastore

- `user_searches.json` — A single Sherlock username search request/run, including whether NSFW platforms were included and summary counts. (18 rows; fields: ['id', 'username', 'include_nsfw', 'status', 'sites_checked', 'matches_found', 'error_message', 'request_fingerprint', 'platform_catalog_version', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: username length between 1 and 64
  - constraint: username matches regex ^[A-Za-z0-9_\.\-]+$
  - constraint: sites_checked >= 0
  - constraint: matches_found >= 0
- `platforms.json` — Catalog of Sherlock-supported sites/platforms that can be checked for username presence. (18 rows; fields: ['id', 'site_key', 'display_name', 'base_url', 'profile_url_template', 'is_nsfw', 'enabled', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(site_key)
  - constraint: display_name length between 1 and 128
  - constraint: base_url starts with 'http://' or 'https://'
  - constraint: profile_url_template contains '{username}'
- `search_results.json` — Per-platform outcome for a given user search run, including the resolved URL and match status. (18 rows; fields: ['id', 'search_id', 'platform_id', 'checked_username', 'profile_url', 'is_found', 'http_status', 'confidence', 'status', 'error_message', 'checked_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'checked', 'error', 'skipped']
  - constraint: foreign key(search_id) references user_searches(id) on delete cascade
  - constraint: foreign key(platform_id) references platforms(id) on delete restrict
  - constraint: unique(search_id, platform_id)
  - constraint: profile_url starts with 'http://' or 'https://'
- `api_keys.json` — API keys used to authenticate and rate-limit access to the MCP server tools. (18 rows; fields: ['id', 'key_prefix', 'key_hash', 'status', 'label', 'requests_per_minute', 'daily_search_limit', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_prefix)
  - constraint: unique(key_hash)
  - constraint: requests_per_minute >= 1 AND requests_per_minute <= 6000
  - constraint: daily_search_limit >= 0
- `api_usage_events.json` — Append-only log of tool invocations used for rate limiting, quotas, and auditing. (18 rows; fields: ['id', 'api_key_id', 'search_id', 'tool_name', 'username', 'include_nsfw', 'response_status', 'results_count', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `response_status`: ['ok', 'invalid_request', 'rate_limited', 'quota_exceeded', 'error']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: latency_ms IS NULL OR latency_ms >= 0
  - constraint: results_count IS NULL OR results_count >= 0
  - constraint: username length between 1 and 64

## Business rules enforced by the tools

- For get_links(username), the system must create (or reuse via request_fingerprint) a user_searches row with include_nsfw=false and return only search_results where is_found=true and the joined platforms.is_nsfw=false.
- For get_nsfw_links(username), the system must create (or reuse via request_fingerprint) a user_searches row with include_nsfw=true and return search_results where is_found=true across both SFW and NSFW platforms.
- A platform check result must not be inserted unless the referenced user_searches and platforms rows exist; deleting a user_searches row must delete its search_results (cascade).
- For any given search_id, there can be at most one search_results row per platform_id (unique(search_id, platform_id)).
- When user_searches.status transitions to succeeded, sites_checked must equal the count of related search_results rows whose status in ('checked','error','skipped'), and matches_found must equal the count of related search_results rows with is_found=true.
- If include_nsfw=false for a search run, the executor must mark NSFW platforms as skipped (status='skipped') and must not return them from get_links responses.
- If an API key is revoked, calls using it must be rejected and logged with response_status='invalid_request' (or 'error' per implementation), and no new user_searches row may be created for that call.
- Rate limiting must enforce api_keys.requests_per_minute based on api_usage_events per api_key_id in a rolling 60-second window; if exceeded, log response_status='rate_limited' and do not execute the search.
- Daily quota must enforce api_keys.daily_search_limit based on count of api_usage_events with response_status='ok' for that api_key_id within the current UTC day; if exceeded, log response_status='quota_exceeded' and do not execute the search.
- Input validation: username must be non-empty, max 64 chars, and match ^[A-Za-z0-9_\.\-]+$; invalid input must be logged with response_status='invalid_request' and must not create search_results rows.