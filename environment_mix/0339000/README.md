# Cloudflare MCP Server for IDE — local MCP environment

This backend models a Cloudflare MCP gateway used by an IDE to manage Cloudflare resources (KV, Workers, R2, D1) and to retrieve analytics. It stores the Cloudflare account connection, resource inventories (names/ids/metadata), and an auditable operation log so each tool call can be executed and traced with lifecycle status, errors, and quotas.

Repository: https://github.com/GutMutCode/mcp-server-cloudflare
Homepage: https://smithery.ai/server/@GutMutCode/mcp-server-cloudflare

## Datastore

- `cf_accounts.json` — Connected Cloudflare accounts (or account contexts) used by the MCP server to authenticate and scope all operations. (12 rows; fields: ['id', 'cloudflare_account_id', 'display_name', 'auth_type', 'api_token_ref', 'api_key_ref', 'api_email', 'status', 'last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(cloudflare_account_id)
  - constraint: auth_type = 'api_token' implies api_token_ref is not null
  - constraint: auth_type = 'api_key_email' implies (api_key_ref is not null and api_email is not null)
- `cf_workers.json` — Inventory of Cloudflare Workers scripts for connected accounts; stores script metadata, bindings, compatibility settings, and last known content hash for drift detection. (29 rows; fields: ['id', 'account_id', 'script_name', 'status', 'compatibility_date', 'compatibility_flags', 'bindings', 'last_content_sha256', 'last_deployed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, script_name)
  - constraint: compatibility_flags defaults to []
  - constraint: bindings defaults to []
- `cf_kv_namespaces_and_keys.json` — KV namespaces and key metadata for connected accounts. Values are not stored by default; only key listings and optional cached values for recent reads. (34 rows; fields: ['id', 'account_id', 'namespace_id', 'namespace_title', 'key', 'status', 'last_seen_at', 'cached_value', 'cached_value_encoding', 'cached_value_bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleted']
  - constraint: unique(account_id, namespace_id, key)
  - constraint: cached_value_bytes is null or cached_value_bytes >= 0
  - constraint: cached_value_bytes is null or cached_value_bytes <= 65536
- `cf_r2_buckets_and_objects.json` — R2 buckets and object metadata for connected accounts. Stores bucket inventory and optionally object listings and small cached payloads for recent reads. (31 rows; fields: ['id', 'account_id', 'bucket_name', 'object_key', 'entity_type', 'status', 'etag', 'size_bytes', 'content_type', 'last_modified_at', 'cached_body_base64', 'cached_body_bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: entity_type = 'bucket' implies object_key is null
  - constraint: entity_type = 'object' implies object_key is not null
  - constraint: unique(account_id, bucket_name, object_key)
  - constraint: cached_body_bytes is null or cached_body_bytes >= 0
- `cf_d1_databases_and_queries.json` — D1 database inventory and executed query history (including results metadata) for auditing and IDE visibility. (30 rows; fields: ['id', 'account_id', 'entity_type', 'database_id', 'database_name', 'status', 'sql_text', 'parameters_json', 'result_rows_json', 'result_truncated', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: entity_type = 'database' implies (database_id is not null and database_name is not null and sql_text is null)
  - constraint: entity_type = 'query_execution' implies (database_id is not null and sql_text is not null)
  - constraint: unique(account_id, database_id) where entity_type='database'
  - constraint: duration_ms is null or duration_ms >= 0
- `mcp_operations.json` — Auditable log of tool calls executed by the MCP server, including request/response metadata, quotas, and status transitions for long/failed operations. (35 rows; fields: ['id', 'account_id', 'tool_name', 'status', 'request_json', 'response_json', 'error_message', 'http_status', 'resource_type', 'resource_locator', 'duration_ms', 'idempotency_key', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: request_json defaults to {}
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: unique(account_id, idempotency_key) where idempotency_key is not null

## Business rules enforced by the tools

- All tools must execute within the scope of exactly one active cf_accounts row; if account status != 'active', the tool must fail and log an mcp_operations row with status='failed'.
- Every tool invocation must create an mcp_operations row with tool_name set, request_json captured (empty object when tool schema has no properties), status transitions received -> running -> succeeded|failed, and duration_ms recorded.
- worker_put must upsert cf_workers by (account_id, script_name), set status='active', update bindings/compatibility fields, and update last_content_sha256 and last_deployed_at on success; worker_delete must set cf_workers.status='deleted'.
- kv_list should upsert cf_kv_namespaces_and_keys rows (status='present', last_seen_at updated); kv_delete must set status='deleted' for the matching (account_id, namespace_id, key). kv_get/kv_put may update cached_value only if payload size <= 65536 bytes and must set cached_value_bytes accordingly.
- r2_list_buckets must upsert bucket rows (entity_type='bucket', object_key null, status='active'); r2_create_bucket must create/activate a bucket row; r2_delete_bucket must set the bucket row status='deleted' and also mark all object rows under that bucket as status='deleted'.
- r2_list_objects must upsert object rows (entity_type='object') under an active bucket; r2_delete_object must set the object row status='deleted'. r2_get_object/r2_put_object may cache bodies only when size <= 262144 bytes and must set cached_body_bytes.
- d1_list_databases must upsert database rows (entity_type='database', status='active'); d1_create_database must create a database row; d1_delete_database must set status='deleted'.
- d1_query must create a query_execution row (entity_type='query_execution') with status queued->running->succeeded|failed; store result_rows_json only up to a server-defined limit and set result_truncated=true when truncated.
- FK integrity: deleting or revoking a cf_accounts row is not allowed while dependent rows exist; instead set cf_accounts.status='revoked' and keep dependent rows for auditability.
- Uniqueness constraints must be enforced to prevent duplicate inventories: (account_id, script_name) for workers; (account_id, namespace_id, key) for KV keys; (account_id, bucket_name, object_key) for R2; (account_id, database_id) for D1 databases; (account_id, idempotency_key) for operations when provided.