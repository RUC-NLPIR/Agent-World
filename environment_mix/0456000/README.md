# MSSQL Database Connector — local MCP environment

This backend stores credentials/configurations for connecting to external Microsoft SQL Server instances and an audit log of SQL queries executed through the connector. The main workflow is: resolve connection settings (from a stored connection profile or ad-hoc parameters), execute the SQL, and persist an immutable execution record including timing, status, and redacted/structured results metadata.

Repository: https://github.com/knight0zh/mssql-mcp-server
Homepage: https://smithery.ai/server/@knight0zh/mssql-mcp-server

## Datastore

- `workspaces.json` — Tenant boundary for grouping connection profiles, access keys, and query execution logs. (12 rows; fields: ['id', 'name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: name length between 1 and 128
- `api_keys.json` — API keys used by clients to authenticate to the connector service; used for authorization and rate limiting. (17 rows; fields: ['id', 'workspace_id', 'key_hash', 'name', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: name length between 1 and 128
- `connection_profiles.json` — Saved MSSQL connection configurations (host/port/db/user + secret reference), optionally including encryption settings. Used to avoid passing credentials on every request; the tool can still accept ad-hoc connection parameters. (35 rows; fields: ['id', 'workspace_id', 'name', 'host', 'port', 'database', 'username', 'password_secret_ref', 'encrypt', 'trust_server_certificate', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: port between 1 and 65535
  - constraint: database length between 1 and 128
- `query_executions.json` — Immutable audit log of each MSSQL query executed via the tool, including how the connection was supplied (connection string vs individual params), redacted connection metadata, timing, and outcomes. (38 rows; fields: ['id', 'workspace_id', 'api_key_id', 'connection_profile_id', 'connection_mode', 'connection_string_redacted', 'host', 'port', 'database', 'username', 'encrypt', 'trust_server_certificate', 'query_text', 'status', 'started_at', 'finished_at', 'duration_ms', 'rows_returned', 'bytes_returned', 'result_preview_json', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete set null
  - constraint: foreign key (connection_profile_id) references connection_profiles(id) on delete set null
  - constraint: duration_ms >= 0
- `usage_counters.json` — Aggregated usage for enforcing quotas and rate limits per workspace and API key. (24 rows; fields: ['id', 'workspace_id', 'api_key_id', 'window_start_at', 'window_seconds', 'queries_count', 'errors_count', 'rows_returned_total', 'bytes_returned_total', 'created_at', 'updated_at'])
  - lifecycle `window_seconds`: []
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(workspace_id, api_key_id, window_start_at, window_seconds)
  - constraint: window_seconds in (60, 300, 3600, 86400)

## Business rules enforced by the tools

- The query tool must accept either (a) connectionString or (b) host+username+password; requests missing both modes are rejected.
- Raw passwords must never be persisted; if a connection profile is created/updated, the password is stored only in an external secret store and referenced by password_secret_ref.
- For ad-hoc requests using host/username/password, the service may log host/port/database/username but must not log the password; connectionString must be stored only in redacted form with credentials removed.
- If port is omitted, it defaults to 1433; if database is omitted, it defaults to 'master'; if encrypt is omitted, it defaults to false; if trustServerCertificate is omitted, it defaults to true, and the resolved values are recorded on query_executions.
- Every query invocation creates a query_executions row in status 'queued' or 'running', then transitions to exactly one terminal state: succeeded, failed, or cancelled; terminal states are immutable.
- A workspace in status 'suspended' or 'deleted' cannot execute queries; an api_key in status 'revoked' cannot execute queries.
- Quota enforcement: for each workspace (and optionally api_key), queries_count in the active window must not exceed the configured limit (implementation-defined); if exceeded, the execution is rejected and no 'running' execution may start.
- Result logging must be bounded: result_preview_json is optional and must be capped by size (e.g., <= 64KB serialized) and row count (e.g., <= 100 rows); otherwise store only rows_returned/bytes_returned metadata.
- Connection_profiles in status 'disabled' or 'deleted' cannot be used for query execution.
- FK integrity must be maintained: query_executions.workspace_id must always reference an existing workspace; if an api_key is deleted, historical query_executions.api_key_id is set to null.