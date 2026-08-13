# Adb MySQL MCP Server — local MCP environment

This backend models a managed gateway that accepts SQL from clients and executes it against an Alibaba Cloud AnalyticDB for MySQL cluster, while recording query history, plans, and runtime execution statistics. The main workflows are: authenticate a caller, submit a SQL statement for execution, retrieve the optimizer query plan (estimated), and retrieve the actual execution plan including runtime metrics.

Repository: https://github.com/aliyun/alibabacloud-adb-mysql-mcp-server
Homepage: https://smithery.ai/server/@aliyun/alibabacloud-adb-mysql-mcp-server

## Datastore

- `projects.json` — Tenant/workspace container that owns database connections, API credentials, and query history for Adb MySQL MCP Server usage. (18 rows; fields: ['id', 'name', 'status', 'default_connection_id', 'retention_days', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: retention_days >= 1 and retention_days <= 3650
  - constraint: fk(default_connection_id) references db_connections(id) on delete set null
- `db_connections.json` — Connection profiles to AnalyticDB for MySQL (endpoint, db name, user), used as the execution target for SQL statements. (18 rows; fields: ['id', 'project_id', 'name', 'engine', 'host', 'port', 'database_name', 'username', 'password_secret_ref', 'tls_mode', 'status', 'last_tested_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: fk(project_id) references projects(id) on delete cascade
  - constraint: unique(project_id, name)
  - constraint: port >= 1 and port <= 65535
- `api_keys.json` — API credentials used to authenticate callers of the MCP tools and to scope access to a project and (optionally) a specific connection. (19 rows; fields: ['id', 'project_id', 'name', 'key_hash', 'status', 'allowed_connection_id', 'allow_readonly_only', 'rate_limit_per_minute', 'max_rows_returned', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: fk(project_id) references projects(id) on delete cascade
  - constraint: fk(allowed_connection_id) references db_connections(id) on delete set null
  - constraint: unique(project_id, name)
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
- `sql_executions.json` — Canonical record of every SQL statement submitted via the MCP server, including execution status, results metadata, and any captured plans (estimated and actual). This collection serves execute_sql, get_query_plan, and get_execution_plan. (18 rows; fields: ['id', 'project_id', 'connection_id', 'api_key_id', 'tool_name', 'sql_text', 'sql_fingerprint', 'status', 'statement_type', 'requested_at', 'started_at', 'finished_at', 'duration_ms', 'rows_returned', 'rows_affected', 'result_truncated', 'result_format', 'result_inline_json', 'result_external_ref', 'error_code', 'error_message', 'query_plan_text', 'execution_plan_text', 'runtime_stats', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(project_id) references projects(id) on delete cascade
  - constraint: fk(connection_id) references db_connections(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: duration_ms is null or duration_ms >= 0

## Business rules enforced by the tools

- All tool calls must authenticate via an api_keys record with status='active' unless explicitly configured for internal mode; on each successful auth, api_keys.last_used_at must be updated.
- For any tool call, the resolved project must be projects.status='active'. If projects.status!='active', the request must be rejected.
- A request must resolve a connection_id either from api_keys.allowed_connection_id (if set) or projects.default_connection_id; if neither exists, the request must be rejected.
- If api_keys.allow_readonly_only=true, sql_executions.statement_type must be one of ('select','explain','show'); otherwise the request must be rejected before execution.
- execute_sql must create a sql_executions row with tool_name='execute_sql', persist sql_text and sql_fingerprint, and transition status queued->running->(succeeded|failed|cancelled).
- get_query_plan must either (a) create a sql_executions row with tool_name='get_query_plan' and populate query_plan_text from an EXPLAIN-like command, or (b) reuse an existing sql_executions row with matching (project_id, connection_id, sql_fingerprint) created within the retention window and return its query_plan_text if present.
- get_execution_plan must either (a) create a sql_executions row with tool_name='get_execution_plan' and populate execution_plan_text and runtime_stats from a profiling/ANALYZE mechanism, or (b) reuse an existing qualifying sql_executions row with execution_plan_text present; if the underlying database does not provide runtime stats, execution_plan_text must still be recorded (possibly with a 'not_supported' marker in runtime_stats).
- Rate limiting: for a given api_key_id, the number of sql_executions with requested_at within the last 60 seconds must not exceed api_keys.rate_limit_per_minute; excess calls must be rejected and must not create a sql_executions row.
- Result limiting: for execute_sql, rows_returned must not exceed api_keys.max_rows_returned; if the database returns more, the service must truncate and set result_truncated=true.
- Data retention: sql_executions older than projects.retention_days must be purged (or hard-deleted) along with any referenced external result objects; purging must not violate FK constraints.
- FK integrity: sql_executions.project_id must match the owning project_id of sql_executions.connection_id; otherwise the insert/update must be rejected.