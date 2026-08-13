# Limitless AI Lifelog Access — local MCP environment

This backend stores users' Limitless AI lifelog entries (recorded moments) and supports listing all entries, retrieving a single entry, and searching across entry content/summaries. It also maintains API clients/keys for authentication and keeps an audit trail of searches for rate limiting, analytics, and debugging.

Repository: https://github.com/Hint-Services/mcp-limitless
Homepage: https://smithery.ai/server/@Hint-Services/mcp-limitless

## Datastore

- `api_clients.json` — API clients/workspaces that call the service. Owns API keys and scopes; used for authentication, tenancy, and rate limiting. (12 rows; fields: ['id', 'name', 'status', 'rate_limit_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 100000
- `api_keys.json` — API keys used to authenticate requests to getLifelogs/getLifelogEntry/searchLifelogs. Stored as hashes; plaintext only shown at creation time (not modeled here). (32 rows; fields: ['id', 'client_id', 'key_hash', 'key_prefix', 'status', 'scopes', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, client_id)
  - constraint: expires_at is null or expires_at > created_at
- `lifelog_entries.json` — Core lifelog 'moments' recorded by a Limitless AI pendant. Supports listing, single-entry retrieval, and search across summary/content. (33 rows; fields: ['id', 'client_id', 'source_provider', 'provider_entry_id', 'status', 'started_at', 'ended_at', 'title', 'summary', 'content_text', 'language', 'tags', 'participants', 'location', 'raw_payload', 'search_tsv', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'processing', 'redacted', 'deleted']
  - constraint: unique(client_id, source_provider, provider_entry_id)
  - constraint: ended_at is null or started_at is null or ended_at >= started_at
  - constraint: status != 'available' or (summary is not null or content_text is not null)
- `lifelog_entry_assets.json` — Child records for media/assets attached to a lifelog entry (audio, images, external links). Used by getLifelogEntry for detailed views. (35 rows; fields: ['id', 'entry_id', 'asset_type', 'status', 'uri', 'mime_type', 'size_bytes', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'missing', 'deleted']
  - constraint: size_bytes is null or size_bytes >= 0
  - constraint: status != 'available' or uri is not null
- `search_requests.json` — Audit log of search operations. Supports monitoring, rate limiting, and debugging for searchLifelogs; can also be used to cache results. (36 rows; fields: ['id', 'client_id', 'api_key_id', 'status', 'query_text', 'filters', 'limit', 'offset', 'results_count', 'latency_ms', 'error_code', 'created_at', 'updated_at'])
  - lifecycle `status`: ['completed', 'failed', 'rate_limited']
  - constraint: limit >= 1 and limit <= 200
  - constraint: offset >= 0
  - constraint: results_count is null or results_count >= 0
  - constraint: latency_ms is null or latency_ms >= 0

## Business rules enforced by the tools

- All tool calls (getLifelogs, getLifelogEntry, searchLifelogs) must authenticate via an active api_keys row whose client_id references an api_clients row with status=active.
- Requests authenticated by api_keys with status in (revoked, expired) must be rejected and api_keys.last_used_at must not be updated.
- getLifelogs returns lifelog_entries for the caller's client_id where status in (available, redacted) and excludes status=deleted by default.
- getLifelogEntry returns a single lifelog_entries row by id only if it belongs to the caller's client_id; if found and not deleted, it may include child lifelog_entry_assets where status != deleted.
- searchLifelogs performs full-text search over lifelog_entries.summary and lifelog_entries.content_text (or lifelog_entries.search_tsv) scoped to the caller's client_id and excluding deleted entries; it must write a search_requests row for every invocation with status completed/failed/rate_limited.
- Rate limiting: within any rolling 60-second window, the number of tool invocations for a client_id must not exceed api_clients.rate_limit_per_minute; excess requests must be recorded as search_requests.status=rate_limited (for search) and rejected for other tools.
- Idempotent ingestion/upsert (internal): for a given (client_id, source_provider, provider_entry_id) there must be at most one lifelog_entries row; updates must bump updated_at and may transition status according to the lifecycle rules.
- When lifelog_entries.status='available', at least one of summary or content_text must be non-null; when status='deleted', content_text and summary may be nulled/redacted but the row must remain for referential integrity.
- Foreign key integrity must be enforced: lifelog_entry_assets.entry_id must reference an existing lifelog_entries.id; deleting an entry must not physically delete assets—assets must be transitioned to status=deleted (soft delete) or remain but be excluded from reads.