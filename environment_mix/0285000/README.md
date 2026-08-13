# MySQL Database Access Server — local MCP environment

This backend models a MySQL Database Access Server that executes SQL statements on behalf of authenticated clients and keeps an auditable history of what was executed, against which schema objects, and with what outcome. Core workflows are: define/track logical databases and tables, execute DDL/DML requests (create/insert/update/delete), and store per-request execution logs, including affected rows and errors.

Repository: https://github.com/michael7736/mysql-mcp-server
Homepage: https://smithery.ai/server/@michael7736/mysql-mcp-server

## Datastore

- `api_keys.json` — API keys used to authenticate callers of the MySQL access server, including status and quota limits for request logging and rate controls. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'name', 'status', 'requests_per_minute_limit', 'daily_requests_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: requests_per_minute_limit >= 1 and requests_per_minute_limit <= 6000
  - constraint: daily_requests_limit >= 1 and daily_requests_limit <= 1000000
- `mysql_databases.json` — Logical MySQL databases/schemas that the server can target. Used to associate DDL/DML actions and aid in authorization and auditing. (12 rows; fields: ['id', 'database_name', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['enabled', 'disabled']
  - constraint: unique(database_name)
- `mysql_tables.json` — Metadata registry of tables created/known through this service (best-effort; actual DDL is source-of-truth). Supports auditing and mapping create_table operations to concrete schema objects. (29 rows; fields: ['id', 'database_id', 'table_name', 'engine', 'table_schema_json', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'dropped']
  - constraint: unique(database_id, table_name)
  - constraint: fk(database_id) references mysql_databases(id) on delete restrict
- `sql_requests.json` — Canonical record of each tool invocation that executes SQL, including the raw SQL text (or derived SQL), tool name, and execution state. This table is the main audit log powering all 5 tools. (40 rows; fields: ['id', 'api_key_id', 'database_id', 'table_id', 'tool_name', 'operation_type', 'sql_text', 'parameters_json', 'status', 'started_at', 'finished_at', 'duration_ms', 'rows_affected', 'result_set_json', 'result_truncated', 'error_code', 'error_message', 'client_metadata_json', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(database_id) references mysql_databases(id) on delete set null
  - constraint: fk(table_id) references mysql_tables(id) on delete set null
  - constraint: duration_ms is null or duration_ms >= 0
- `request_table_effects.json` — Many-to-many mapping between SQL requests and the tables they touched. Useful when run_sql_query includes joins/multi-table statements or when the primary table cannot be determined reliably. (32 rows; fields: ['id', 'sql_request_id', 'table_id', 'effect_type', 'created_at', 'updated_at'])
  - constraint: fk(sql_request_id) references sql_requests(id) on delete cascade
  - constraint: fk(table_id) references mysql_tables(id) on delete restrict
  - constraint: unique(sql_request_id, table_id, effect_type)

## Business rules enforced by the tools

- Every tool invocation (run_sql_query/create_table/insert_data/update_data/delete_data) must create exactly one sql_requests row with tool_name set accordingly.
- sql_requests.sql_text must be non-empty and must not exceed 1,000,000 characters; if larger, the server must reject the request.
- API key authentication must resolve to an api_keys row with status='active'; otherwise the request is rejected and no sql_requests row is created.
- Rate limits: for a given api_key_id, if requests_per_minute_limit or daily_requests_limit would be exceeded, the server must reject the request and optionally record a failed sql_requests row with error_code='quota_exceeded'.
- Status transitions for sql_requests must follow the declared lifecycle; direct transitions from queued to succeeded/failed are not allowed unless started_at is set in the same transaction (i.e., treated as running).
- On sql_requests.status change to 'running', started_at must be set; on change to any terminal state (succeeded/failed/cancelled), finished_at must be set and duration_ms computed.
- For create_table calls that successfully create a new table, a mysql_tables row must exist with status='active' and (database_id, table_name) unique; if the table already exists, the request must fail unless the SQL explicitly uses IF NOT EXISTS (then rows_affected may be 0).
- For delete_data/update_data/insert_data calls, rows_affected must be populated from the MySQL driver response when available; if not available it may be null but must never be negative.
- If the server stores query results, sql_requests.result_set_json must be capped (e.g., max 5MB); if capped, result_truncated must be true.
- If a request touches multiple tables (e.g., JOIN/UPDATE with JOIN), the server should populate request_table_effects with one row per table and best-effort effect_type; uniqueness per (sql_request_id, table_id, effect_type) must be preserved.
- Dropping a table (DDL DROP TABLE) should mark mysql_tables.status='dropped' (best-effort) and must not delete the mysql_tables row to preserve auditability.