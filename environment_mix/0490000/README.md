# Raindrop.io Integration — local MCP environment

This backend stores user-linked Raindrop.io data needed by the integration: collections (folders), bookmarks (raindrops), and API/auth metadata for calling Raindrop.io on a user's behalf. Main workflows are: authenticate a user, sync/list collections, create bookmarks into a collection, and search bookmarks by indexed content.

Repository: https://github.com/hiromitsusasaki/raindrop-io-mcp-server
Homepage: https://smithery.ai/server/@hiromitsusasaki/raindrop-io-mcp-server

## Datastore

- `accounts.json` — Represents a local user/workspace that has connected a Raindrop.io account and can perform API actions. Holds identity and connection state. (18 rows; fields: ['id', 'provider', 'raindrop_user_id', 'email', 'display_name', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(provider, raindrop_user_id) where raindrop_user_id is not null
  - constraint: status in ('active','revoked','error')
- `api_credentials.json` — Stores Raindrop.io API tokens/credentials for an account, including rotation and revocation metadata. Used by all tools to call the Raindrop.io API. (19 rows; fields: ['id', 'account_id', 'auth_type', 'access_token_ciphertext', 'token_last4', 'status', 'rotated_from_credential_id', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'rotated', 'revoked']
  - constraint: foreign key(account_id) references accounts(id) on delete cascade
  - constraint: at most 1 active credential per account_id (partial unique index on (account_id) where status='active')
  - constraint: status in ('active','rotated','revoked')
- `collections.json` — Caches Raindrop.io collections/folders for each account. Served by list-collections and used as a target for create-bookmark. (18 rows; fields: ['id', 'account_id', 'raindrop_collection_id', 'title', 'description', 'parent_raindrop_collection_id', 'is_public', 'sort', 'status', 'synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: foreign key(account_id) references accounts(id) on delete cascade
  - constraint: unique(account_id, raindrop_collection_id)
  - constraint: title <> ''
  - constraint: sort is null or sort >= 0
- `bookmarks.json` — Caches Raindrop.io bookmarks (raindrops). Used for create-bookmark (insert + remote create) and search-bookmarks (query local cache and/or store results of remote searches). (20 rows; fields: ['id', 'account_id', 'collection_id', 'raindrop_id', 'url', 'title', 'excerpt', 'tags', 'search_text', 'cover_url', 'created_at_remote', 'last_accessed_at_remote', 'status', 'error_message', 'synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'creating', 'active', 'deleted', 'error']
  - constraint: foreign key(account_id) references accounts(id) on delete cascade
  - constraint: foreign key(collection_id) references collections(id) on delete set null
  - constraint: url <> ''
  - constraint: unique(account_id, raindrop_id) where raindrop_id is not null
- `search_queries.json` — Stores audit/history of search-bookmarks calls and supports rate limiting, caching, and reproducibility of search results. (18 rows; fields: ['id', 'account_id', 'query_text', 'collection_id', 'executed_via', 'result_count', 'status', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'completed', 'failed']
  - constraint: foreign key(account_id) references accounts(id) on delete cascade
  - constraint: foreign key(collection_id) references collections(id) on delete set null
  - constraint: result_count >= 0
  - constraint: executed_via in ('remote','local','hybrid')

## Business rules enforced by the tools

- All tools require an accounts row with status='active' and an api_credentials row with status='active' for that account; otherwise the call fails as unauthorized.
- list-collections reads from collections where account_id matches and status != 'deleted'; if cache is stale (accounts.last_sync_at older than a configured TTL), the implementation may refresh from Raindrop.io and upsert collections by (account_id, raindrop_collection_id).
- create-bookmark creates a bookmarks row in status='creating' (or 'draft' if missing required URL), then attempts remote creation; on success it sets raindrop_id, status='active', created_at_remote, and links collection_id when resolvable; on failure it sets status='error' with error_message.
- create-bookmark must reject empty url and must enforce a maximum URL length (e.g., 2048) and maximum tags count (e.g., 100) to prevent abuse.
- search-bookmarks always writes a search_queries audit row: status transitions running->completed/failed; result_count must equal the number of returned bookmark records.
- search-bookmarks may execute against local cache using bookmarks.search_text (case-insensitive substring) and/or remote API; when remote results include new/updated raindrops, bookmarks are upserted by (account_id, raindrop_id).
- A bookmark with status='deleted' must not be returned by search-bookmarks unless the implementation explicitly supports include_deleted (not exposed in this tool surface).
- There must be at most one active credential per account; rotating a credential sets prior status to 'rotated' and inserts a new active credential.
- Foreign-key integrity is enforced: bookmarks.account_id must exist; bookmarks.collection_id (if set) must belong to the same account_id (enforced via application check or composite FK).
- Rate limiting/quota: each account is limited to N remote Raindrop.io requests per minute (configured); exceeding this causes create-bookmark/search-bookmarks/list-collections to either use cached data or fail with a throttling error while recording the attempt (search_queries for searches).