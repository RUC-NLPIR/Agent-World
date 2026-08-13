# SQLite Database Server — local MCP environment

This backend models a multi-tenant SQLite database server that exposes tools to create tables, run read/write SQL, inspect schema, and maintain a simple memo of business insights. The main workflows are: authenticate a client, execute SQL statements against a specific database, record execution/audit logs, and store insights appended over time.

Repository: https://github.com/isaacgounton/sqlite-mcp-server
Homepage: https://smithery.ai/server/@isaacgounton/sqlite-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace container for databases, API keys, and audit context. (12 rows; fields: ['id', 'name', 'status', 'default_database_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_database_id is null OR default_database_id references databases(id)
  - constraint: status in ('active','suspended','deleted')
- `api_keys.json` — API credentials used to access the server and authorize SQL execution within a workspace. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'scopes', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: status in ('active','revoked')
  - constraint: json_array_length(scopes) >= 1
- `databases.json` — SQLite database instances managed by the server (typically one file per database). (12 rows; fields: ['id', 'workspace_id', 'name', 'status', 'file_path', 'pragma_settings', 'max_result_rows', 'created_at', 'updated_at'])
  - lifecycle `status`: ['online', 'read_only', 'offline', 'deleted']
  - constraint: unique(workspace_id, name)
  - constraint: max_result_rows between 1 and 100000
  - constraint: status in ('online','read_only','offline','deleted')
  - constraint: file_path <> ''
- `db_tables.json` — Server-side catalog cache of tables within each SQLite database to support list/describe operations and change tracking. (36 rows; fields: ['id', 'database_id', 'name', 'type', 'status', 'create_sql', 'schema_json', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'dropped']
  - constraint: unique(database_id, name)
  - constraint: type in ('table','view')
  - constraint: status in ('present','dropped')
- `sql_executions.json` — Audit log of all tool-driven SQL executions (read_query, write_query, create_table, list_tables, describe_table) including timing, errors, and affected object metadata. (33 rows; fields: ['id', 'workspace_id', 'database_id', 'api_key_id', 'tool_name', 'sql_text', 'status', 'error_message', 'rows_returned', 'rows_affected', 'duration_ms', 'table_name_hint', 'result_preview_json', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: tool_name in ('read_query','write_query','create_table','list_tables','describe_table')
  - constraint: duration_ms is null OR duration_ms >= 0
  - constraint: rows_returned is null OR rows_returned >= 0
  - constraint: rows_affected is null OR rows_affected >= 0
- `insights.json` — Append-only memo of business insights added via append_insight; can be used by the system to remember findings about the data over time. (26 rows; fields: ['id', 'workspace_id', 'database_id', 'status', 'insight_text', 'source_execution_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: insight_text <> ''
  - constraint: status in ('active','archived')

## Business rules enforced by the tools

- All tool calls must resolve a workspace via an active api_keys row; revoked keys are rejected.
- If workspaces.status != 'active', all SQL tools are rejected; append_insight is allowed only when status='active'.
- If databases.status='offline' or 'deleted', all SQL tools against that database are rejected.
- If databases.status='read_only', write_query and create_table are rejected; read_query, list_tables, describe_table are allowed.
- read_query may execute only SELECT/WITH/EXPLAIN statements; any statement that mutates schema/data is rejected.
- write_query may execute only INSERT/UPDATE/DELETE (and optionally transaction wrappers); SELECT is rejected for write_query.
- create_table may execute only CREATE TABLE (and optionally CREATE INDEX); DROP/ALTER is rejected unless explicitly enabled by server configuration.
- list_tables must return schema objects from sqlite_master where type in ('table','view') excluding internal SQLite tables unless a debug flag is enabled; the result set is also used to refresh db_tables catalog entries.
- describe_table must verify the requested table exists (db_tables.status='present' after refresh) before returning PRAGMA table_info and related metadata; requests for missing tables return a not-found error.
- Each successful SQL tool invocation must create a sql_executions row and transition status through queued->running->(succeeded|failed); failed executions must store error_message.
- Result payload sizes are capped: rows_returned must be <= databases.max_result_rows; if underlying SQL returns more, the server truncates and records the truncated count in result_preview_json.
- append_insight creates an insights row with status='active' and non-empty insight_text; it must not overwrite prior insights (append-only semantics).
- FK integrity: api_keys.workspace_id must exist; databases.workspace_id must exist; db_tables.database_id must exist; sql_executions.workspace_id/database_id must exist and must belong to the same workspace; insights.workspace_id must exist and if insights.database_id is set it must belong to the same workspace.
- Uniqueness: databases(name) is unique per workspace; db_tables(name) is unique per database; api_keys(name) is unique per workspace; api_keys.key_hash is globally unique.