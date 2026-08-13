# Microsoft SQL Server MCP Server — local MCP environment

This backend stores connection configurations, authenticated sessions, and a complete audit trail of SQL executed through the MCP tool. The main workflow is: a client opens/uses a session, submits ad-hoc SQL via execute_sql, the server runs it against a configured Microsoft SQL Server data source, and records results metadata, row samples, and errors for observability and governance.

Repository: https://github.com/leopeng1995/mssql-mcp-server
Homepage: https://smithery.ai/server/@leopeng1995/mssql-mcp-server

## Datastore

- `workspaces.json` — Tenant boundary for grouping data sources, sessions, policies, and execution history for the MCP server deployment. (12 rows; fields: ['id', 'name', 'status', 'default_datasource_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_datasource_id references datasources.id
- `api_keys.json` — API keys used by clients to authenticate to the MCP server before executing SQL. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'scopes', 'expires_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: workspace_id references workspaces.id
  - constraint: expires_at is null OR expires_at > created_at
- `datasources.json` — Configured Microsoft SQL Server connection targets used by the MCP server to execute queries. (12 rows; fields: ['id', 'workspace_id', 'name', 'status', 'server_host', 'server_port', 'database_name', 'auth_mode', 'username', 'password_secret_ref', 'encrypt', 'trust_server_certificate', 'connection_options', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(workspace_id, name)
  - constraint: workspace_id references workspaces.id
  - constraint: server_port >= 1 AND server_port <= 65535
  - constraint: encrypt in (true,false)
- `sessions.json` — Short-lived authenticated sessions created after a valid API key is presented; used to associate execute_sql calls, defaults, and policy enforcement. (20 rows; fields: ['id', 'workspace_id', 'api_key_id', 'datasource_id', 'status', 'client_info', 'issued_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: workspace_id references workspaces.id
  - constraint: api_key_id references api_keys.id
  - constraint: datasource_id references datasources.id
  - constraint: expires_at > issued_at
- `sql_executions.json` — Immutable execution log for every execute_sql tool call, including the SQL text, parameters (if any), timing, outcome, and a bounded result sample for debugging. (41 rows; fields: ['id', 'workspace_id', 'session_id', 'datasource_id', 'tool_name', 'status', 'sql_text', 'sql_fingerprint', 'request_context', 'started_at', 'finished_at', 'duration_ms', 'rows_affected', 'result_set_count', 'result_columns', 'result_rows_sample', 'result_truncated', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: workspace_id references workspaces.id
  - constraint: session_id references sessions.id
  - constraint: datasource_id references datasources.id
  - constraint: duration_ms is null OR duration_ms >= 0

## Business rules enforced by the tools

- execute_sql must create a sql_executions row with tool_name='execute_sql' and status='queued' before any database call is attempted.
- execute_sql must resolve datasource_id from sessions.datasource_id; if null, use workspaces.default_datasource_id; if still null, the call fails and the execution is marked failed with an error_message indicating missing datasource.
- A session with status != 'active' or now() >= sessions.expires_at cannot be used to execute SQL; attempts must be rejected and logged as failed executions.
- A datasource with status != 'active' cannot be used for execute_sql; attempts must be rejected and logged as failed executions.
- SQL execution status transitions must follow sql_executions.lifecycle.transitions; direct transitions from queued to succeeded are invalid without passing through running (unless the connector returns synchronously and the implementation updates queued->running->succeeded within the same request).
- Result storage must be bounded: result_rows_sample length <= 100 and total serialized size of result_rows_sample + result_columns <= 256KB; if exceeded, set result_truncated=true and store only the first N rows/columns that fit.
- Errors stored in sql_executions.error_message must be sanitized to avoid leaking secrets (e.g., passwords, connection strings, access tokens).
- Only API keys with scope containing 'execute_sql' may create sessions or execute SQL; otherwise the request is rejected.
- Per-workspace safety policy: unless an explicit allowlist exists in configuration, statements containing 'DROP ', 'TRUNCATE ', 'ALTER LOGIN', 'CREATE LOGIN' must be rejected and logged as failed executions (defense-in-depth).
- Concurrency limit: at most 10 sql_executions in status in ('queued','running') per workspace at a time; additional calls must be rejected or queued depending on deployment configuration, but must still be recorded.