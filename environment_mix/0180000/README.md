# Memory Cache Server — local MCP environment

This backend stores cached key/value entries with optional TTL and lifecycle (active/expired/deleted) while tracking cache-wide operational statistics. Core workflows are: write/update an entry (optionally expiring it), read an entry (with lazy-expiration), clear one or all entries, and query aggregated cache stats and counters.

Repository: https://github.com/ibproduct/ib-mcp-cache-server
Homepage: https://smithery.ai/server/@ibproduct/ib-mcp-cache-server

## Datastore

- `cache_entries.json` — Primary key/value cache storage with optional TTL, expiration, and soft deletion for auditability. (18 rows; fields: ['id', 'cache_key', 'value_json', 'value_bytes', 'ttl_seconds', 'expires_at', 'last_accessed_at', 'write_count', 'read_count', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'deleted']
  - constraint: unique(cache_key) where status != 'deleted'
  - constraint: value_bytes >= 0
  - constraint: write_count >= 0
  - constraint: read_count >= 0
- `cache_operations.json` — Append-only log of cache operations for debugging, stats, and audit of mutations/reads. (18 rows; fields: ['id', 'op_type', 'cache_entry_id', 'cache_key', 'ttl_seconds', 'result', 'error_code', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `result`: ['success', 'miss', 'expired', 'error']
  - constraint: op_type in ('store_data','retrieve_data','clear_cache','get_cache_stats')
  - constraint: result in ('success','miss','expired','error')
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: ttl_seconds is null or ttl_seconds > 0
- `cache_stats_snapshots.json` — Periodic or on-demand snapshots used to serve get_cache_stats efficiently and consistently. (18 rows; fields: ['id', 'scope', 'active_keys', 'expired_keys', 'deleted_keys', 'approx_bytes', 'stores_total', 'retrieves_total', 'hits_total', 'misses_total', 'expired_total', 'clears_total', 'last_full_clear_at', 'created_at', 'updated_at'])
  - lifecycle `scope`: ['instance']
  - constraint: active_keys >= 0
  - constraint: expired_keys >= 0
  - constraint: deleted_keys >= 0
  - constraint: approx_bytes >= 0
- `cache_retention_policies.json` — Operational settings governing max sizes and retention of soft-deleted/expired entries for audit and stats stability. (18 rows; fields: ['id', 'name', 'max_entry_bytes', 'max_total_bytes', 'max_keys', 'soft_delete_retention_seconds', 'expired_retention_seconds', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(name)
  - constraint: max_entry_bytes is null or max_entry_bytes > 0
  - constraint: max_total_bytes is null or max_total_bytes > 0
  - constraint: max_keys is null or max_keys > 0

## Business rules enforced by the tools

- store_data(key, value, ttl?): If a non-deleted entry with cache_key=key exists, it is overwritten (value_json, value_bytes, ttl_seconds, expires_at updated), write_count increments, status becomes 'active', deleted_at cleared, updated_at set to now.
- store_data: If ttl is provided it must be > 0; expires_at must be set to now + ttl. If ttl is omitted, ttl_seconds and expires_at must be null.
- retrieve_data(key): If no non-deleted entry exists, return miss and log cache_operations.result='miss'.
- retrieve_data(key): If entry exists and expires_at is not null and now >= expires_at, the entry must transition to status='expired' (if currently active), and the retrieve must return expired (not the value) and log cache_operations.result='expired'.
- retrieve_data(key): If entry is active, return value_json, set last_accessed_at=now, increment read_count, and log cache_operations.result='success'.
- clear_cache(key?): If key is provided and an entry exists with that key and status != 'deleted', it must transition to 'deleted' with deleted_at=now; if not found, operation still succeeds (idempotent) and logs result='success' with cache_entry_id null.
- clear_cache(no key): All entries with status in ('active','expired') must transition to 'deleted' with deleted_at=now in a single logical operation; cache_stats_snapshots.last_full_clear_at must be set to now.
- get_cache_stats: Stats returned must be derivable from cache_stats_snapshots newest row; if no snapshot exists, it must be computed from cache_entries and cache_operations and then written as a snapshot.
- Retention: A background purge may hard-delete rows from cache_entries where status='deleted' and deleted_at < now - soft_delete_retention_seconds, and where status='expired' and expires_at < now - expired_retention_seconds, but only after writing a cache_stats_snapshots row capturing pre/post counts.
- Quota/policy enforcement (when an active cache_retention_policies row exists): store_data must reject writes where value_bytes > max_entry_bytes, or where projected active_keys would exceed max_keys, or projected approx_bytes would exceed max_total_bytes.