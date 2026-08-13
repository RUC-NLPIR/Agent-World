# Unsplash Server — local MCP environment

This backend supports an Unsplash-facing search service that executes photo searches and returns results. It stores API clients/keys, search requests (for auditing and rate limiting), and cached photo metadata to reduce external API calls and improve performance.

Repository: https://github.com/douglarek/unsplash-mcp-server
Homepage: https://smithery.ai/server/@douglarek/unsplash-mcp-server

## Datastore

- `api_clients.json` — Registered clients of the Unsplash Server (e.g., MCP clients). Used for authentication, rate limiting, and attribution of searches. (12 rows; fields: ['id', 'name', 'status', 'default_rate_limit_per_minute', 'notes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(name)
  - constraint: default_rate_limit_per_minute >= 1 and default_rate_limit_per_minute <= 6000
- `api_keys.json` — API keys/tokens used by clients to call this server. Stores hashed secrets and key lifecycle for revocation/rotation. (12 rows; fields: ['id', 'client_id', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: unique(key_prefix)
  - constraint: foreign key(client_id) references api_clients(id) on delete cascade
  - constraint: expires_at is null or expires_at > created_at
- `search_requests.json` — Audit log of search_photos calls. Stores request metadata, computed cache keys, and execution outcomes (including upstream Unsplash calls). (18 rows; fields: ['id', 'client_id', 'api_key_id', 'status', 'query_text', 'page', 'per_page', 'cache_key', 'cache_hit', 'upstream_provider', 'upstream_request_id', 'upstream_status_code', 'error_code', 'error_message', 'result_count', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'rate_limited']
  - constraint: foreign key(client_id) references api_clients(id) on delete set null
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: unique(cache_key, created_at)  -- practical uniqueness for dedupe windows
  - constraint: page is null or page >= 1
- `photos.json` — Cached Unsplash photo metadata (subset) to support returning consistent results and minimizing upstream calls. (18 rows; fields: ['id', 'external_unsplash_id', 'status', 'description', 'user_name', 'user_username', 'url_full', 'url_regular', 'url_small', 'width', 'height', 'color', 'likes', 'unsplash_updated_at', 'cached_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'stale']
  - constraint: unique(external_unsplash_id)
  - constraint: width is null or width > 0
  - constraint: height is null or height > 0
  - constraint: likes is null or likes >= 0
- `search_request_photos.json` — Join table storing which photos were returned for a given search request, preserving ranking/order and enabling reproducible responses and analytics. (18 rows; fields: ['id', 'search_request_id', 'photo_id', 'position', 'source', 'created_at', 'updated_at'])
  - lifecycle `source`: ['cache', 'upstream']
  - constraint: foreign key(search_request_id) references search_requests(id) on delete cascade
  - constraint: foreign key(photo_id) references photos(id) on delete restrict
  - constraint: unique(search_request_id, position)
  - constraint: unique(search_request_id, photo_id)

## Business rules enforced by the tools

- Calling search_photos must create a search_requests row with status=received and then transition to running; it must end in exactly one terminal state: succeeded, failed, or rate_limited.
- If an API key is provided, it must exist, have status=active, and (expires_at is null or expires_at > now()); otherwise the request is rejected and no succeeded search_requests row is written.
- If client_id/api_key_id are present on a search request, api_key_id.client_id must equal client_id.
- Rate limiting: for each api_key_id, the number of search_requests created within a rolling 60-second window must not exceed api_clients.default_rate_limit_per_minute (or an overridden limit if implemented); excess requests must be recorded with status=rate_limited.
- Cache behavior: for a given cache_key, if a recent succeeded search exists within a configured TTL, the server may mark cache_hit=true and reuse stored search_request_photos/photos without calling upstream.
- On succeeded searches, result_count must equal the number of search_request_photos rows for that search_request_id; positions must be contiguous starting at 1.
- photos.external_unsplash_id is the canonical identifier for deduping upstream results; inserts must upsert on external_unsplash_id and update cached_at.
- Deleted photos (photos.status=deleted) must not be newly associated to future succeeded searches; if encountered in cache they must be refreshed from upstream or omitted.