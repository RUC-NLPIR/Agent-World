# Pexels MCP Server — local MCP environment

This backend persists a local, audit-friendly cache of Pexels media (photos/videos) and collections, plus per-client API credentials and request logs. The main workflows are: set/store an API key for a client, execute read-only discovery tools (search/curated/popular/featured/collection media) while caching results, and handle download actions by recording downloadable asset URLs and download events.

Repository: https://github.com/CaullenOmdahl/pexels-mcp-server
Homepage: https://smithery.ai/server/@CaullenOmdahl/pexels-mcp-server

## Datastore

- `api_clients.json` — Represents an MCP caller/client identity (e.g., a workspace, user, or installation) that uses this server. Holds quota settings and is the parent for API keys and request logs. (18 rows; fields: ['id', 'display_name', 'status', 'daily_request_limit', 'monthly_request_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(display_name)
  - constraint: daily_request_limit >= 0
  - constraint: monthly_request_limit >= 0
- `api_keys.json` — Stores Pexels API keys set via setApiKey. Supports rotation and revocation; only one active key per client is allowed. (18 rows; fields: ['id', 'client_id', 'provider', 'api_key_ciphertext', 'api_key_last4', 'status', 'activated_at', 'revoked_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key(client_id) references api_clients(id) on delete cascade
  - constraint: unique(client_id) where status = 'active'
  - constraint: length(api_key_last4) = 4
- `media_items.json` — Canonical cache of Pexels media (photos and videos) and their core metadata used by getPhoto/getVideo and used in search/curated/popular/collection results. (19 rows; fields: ['id', 'provider', 'provider_media_id', 'media_type', 'status', 'url', 'width', 'height', 'duration_seconds', 'photographer_name', 'photographer_url', 'avg_color', 'thumbnail_url', 'assets', 'attribution_required', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'tombstoned']
  - constraint: unique(provider, provider_media_id, media_type)
  - constraint: width is null or width > 0
  - constraint: height is null or height > 0
  - constraint: duration_seconds is null or duration_seconds >= 0
- `collections.json` — Caches Pexels featured/user collections and their metadata for getFeaturedCollections and getCollectionMedia. (18 rows; fields: ['id', 'provider', 'provider_collection_id', 'title', 'description', 'status', 'is_featured', 'media_count', 'cover_media_id', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden', 'deleted']
  - constraint: unique(provider, provider_collection_id)
  - constraint: media_count is null or media_count >= 0
- `request_events.json` — Audit/usage log for every tool invocation. Stores normalized tool name, upstream request/response metadata, and links to cached entities when applicable. (19 rows; fields: ['id', 'client_id', 'api_key_id', 'tool_name', 'status', 'parameters', 'upstream_endpoint', 'upstream_status_code', 'response_bytes', 'latency_ms', 'error_code', 'error_message', 'cached_media_id', 'cached_collection_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'succeeded', 'failed']
  - constraint: foreign key(client_id) references api_clients(id) on delete cascade
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: response_bytes is null or response_bytes >= 0
- `collection_media.json` — Join table mapping cached collections to cached media items in that collection. Used to serve getCollectionMedia efficiently and to retain ordering from upstream. (18 rows; fields: ['id', 'collection_id', 'media_id', 'position', 'added_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: foreign key(collection_id) references collections(id) on delete cascade
  - constraint: foreign key(media_id) references media_items(id) on delete cascade
  - constraint: unique(collection_id, media_id)
  - constraint: position is null or position >= 0

## Business rules enforced by the tools

- setApiKey must create a new api_keys row with provider='pexels' and status='active', and must revoke (status='revoked', revoked_at set) any previously active key for the same client in the same transaction.
- All tools except setApiKey must require the caller's api_clients.status='active' and the existence of exactly one api_keys row with status='active' for that client; otherwise they must record request_events.status='failed' with error_code='API_KEY_MISSING' or 'CLIENT_SUSPENDED'.
- Every tool invocation must create a request_events row in status='received' and then transition to 'succeeded' or 'failed' exactly once; updates must not move from 'succeeded'/'failed' back to 'received'.
- searchPhotos, getCuratedPhotos, searchVideos, getPopularVideos, getFeaturedCollections, and getCollectionMedia must upsert returned entities into media_items/collections and set last_synced_at; they must not create duplicate media_items for the same (provider, provider_media_id, media_type) nor duplicate collections for the same (provider, provider_collection_id).
- getPhoto and getVideo must attempt to read from media_items by (provider_media_id, media_type) and refresh from upstream when missing or stale; on successful fetch, the media_items row must be inserted/updated to status='active'.
- downloadPhoto and downloadVideo must record a request_events row that links cached_media_id to the downloaded item; downloads must not proceed for media_items with status in ('deleted','tombstoned').
- getCollectionMedia must maintain collection_media mappings for returned items; for a given collection, (collection_id, media_id) must be unique and any removal must be represented by transitioning collection_media.status to 'removed' rather than hard delete.
- Quota enforcement: if a client's daily_request_limit or monthly_request_limit would be exceeded by a new request_events row, the tool must fail with error_code='QUOTA_EXCEEDED' and must not call upstream; the failed request must still be logged.
- Sensitive material: api_key_ciphertext must never be returned to tool responses and must be written only by setApiKey; request_events.parameters and error_message must be sanitized to avoid storing plaintext API keys.