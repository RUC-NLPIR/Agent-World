# Database Tools — local MCP environment

This backend powers a MySQL query execution API, storing connection configurations, access credentials, and an audited log of executed SQL statements and their outcomes. The primary workflow is: a client submits a SQL string, the service executes it against a configured MySQL datasource, and the system records the execution metadata, result summary, and any errors for audit and troubleshooting.

Repository: https://github.com/elber-code/database-tools
Homepage: https://smithery.ai/server/@elber-code/database-tools

## Datastore

- `workspaces.json` — Tenant container for isolating datasources, API keys, and query execution logs. (12 rows; fields: ['id', 'name', 'status', 'default_datasource_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_datasource_id references datasources.id and must belong to same workspace
- `api_keys.json` — API credentials used to authenticate callers and enforce quotas for query execution. (19 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, workspace_id)
- `datasources.json` — Configured MySQL endpoints and connection policy used by the mysql tool execution. (12 rows; fields: ['id', 'workspace_id', 'name', 'engine', 'host', 'port', 'database_name', 'username', 'password_ciphertext', 'tls_mode', 'connect_timeout_ms', 'statement_timeout_ms', 'read_only', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(workspace_id, name)
  - constraint: port between 1 and 65535
  - constraint: connect_timeout_ms between 100 and 60000
  - constraint: statement_timeout_ms between 100 and 3600000
- `query_executions.json` — Audit log and result metadata for each executed SQL query submitted via the mysql tool. (36 rows; fields: ['id', 'workspace_id', 'api_key_id', 'datasource_id', 'request_query', 'normalized_query', 'query_fingerprint', 'status', 'started_at', 'finished_at', 'duration_ms', 'rows_affected', 'result_row_count', 'result_truncated', 'result_preview_json', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: rows_affected is null or rows_affected >= 0
  - constraint: result_row_count is null or result_row_count >= 0
  - constraint: finished_at is null or finished_at >= started_at
- `workspace_quotas.json` — Quota and safety limits for query execution per workspace/datasource to protect infrastructure and data. (12 rows; fields: ['id', 'workspace_id', 'scope', 'datasource_id', 'max_requests_per_minute', 'max_concurrent_executions', 'max_result_rows', 'max_result_bytes', 'allow_write_queries', 'created_at', 'updated_at'])
  - lifecycle `scope`: ['workspace', 'datasource']
  - constraint: unique(workspace_id, scope, datasource_id)
  - constraint: max_requests_per_minute between 1 and 60000
  - constraint: max_concurrent_executions between 1 and 1000
  - constraint: max_result_rows between 0 and 1000000

## Business rules enforced by the tools

- mysql tool parameter 'query' MUST be persisted to query_executions.request_query for every request.
- A mysql execution MUST authenticate with an active api_keys row; revoked keys MUST be rejected.
- A mysql execution MUST resolve a target datasource: workspace.default_datasource_id MUST be set and point to an active datasources row, since the tool surface does not accept datasource selection.
- If workspaces.status != 'active' then mysql executions MUST be rejected.
- If datasources.status != 'active' then mysql executions MUST be rejected.
- If datasources.read_only = true OR workspace_quotas.allow_write_queries = false, the service MUST reject non-read-only statements (e.g., INSERT/UPDATE/DELETE/DDL) based on a SQL classifier before execution.
- Before transitioning a query_executions row to 'running', the service MUST enforce max_concurrent_executions for the applicable quota scope (datasource-specific quota if present else workspace quota).
- The service MUST enforce max_requests_per_minute per API key or per workspace (implementation choice) using query_executions.created_at timestamps; requests exceeding the limit MUST be rejected.
- statement_timeout_ms on datasources MUST cap execution duration; if exceeded, query_executions.status MUST transition to 'failed' or 'cancelled' and finished_at MUST be set.
- For successful SELECT queries, result_preview_json MUST be truncated to max_result_rows and max_result_bytes, setting query_executions.result_truncated = true when truncation occurs.
- query_executions.status transitions MUST follow the declared lifecycle; illegal transitions MUST be rejected.
- query_executions.api_key_id and datasource_id MUST belong to the same workspace_id (enforced on write).