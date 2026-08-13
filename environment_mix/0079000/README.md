# MySQL MCP Server — local MCP environment

This backend stores connection sessions to remote MySQL instances and an auditable history of operations performed through the MCP server. Main workflows are: create a connection session (connect_database), run read/write SQL (execute_query) with stored results/metadata, introspect schema (show_tables/describe_table) and then close the session (disconnect_database).

Repository: https://github.com/lhylygr/MySQL_MCP
Homepage: https://smithery.ai/server/@lhylygr/mysql_mcp

## Datastore

- `db_connections.json` — Represents a configured target MySQL database endpoint (host/port/database) and credential reference used to establish sessions. This is not the live socket; it is the reusable connection profile behind connect_database. (18 rows; fields: ['id', 'host', 'port', 'username', 'password_secret_id', 'database_name', 'tls_mode', 'connect_timeout_ms', 'status', 'last_connected_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: required(host, port, username, password_secret_id, database_name, tls_mode, connect_timeout_ms, status)
  - constraint: port >= 1 AND port <= 65535
  - constraint: connect_timeout_ms >= 100 AND connect_timeout_ms <= 600000
  - constraint: unique(host, port, username, database_name)
- `db_sessions.json` — Represents a single live-ish session created by connect_database and closed by disconnect_database. execute_query/show_tables/describe_table run within a session context (typically 'current session' for the caller). (18 rows; fields: ['id', 'connection_id', 'session_token_hash', 'server_thread_id', 'autocommit', 'status', 'connected_at', 'disconnected_at', 'last_activity_at', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['connecting', 'connected', 'disconnecting', 'disconnected', 'error']
  - constraint: required(connection_id, session_token_hash, autocommit, status)
  - constraint: unique(session_token_hash)
  - constraint: FK(connection_id) REFERENCES db_connections(id) ON DELETE RESTRICT
  - constraint: status IN ('connecting','connected','disconnecting','disconnected','error')
- `sql_operations.json` — Audit log of all operations invoked through the MCP tools: execute_query, show_tables, describe_table. Stores the input, outcome, timing, and summary stats. (18 rows; fields: ['id', 'session_id', 'tool_name', 'query_text', 'table_name', 'normalized_fingerprint', 'operation_kind', 'status', 'started_at', 'finished_at', 'duration_ms', 'rows_returned', 'rows_affected', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: required(session_id, tool_name, operation_kind, status)
  - constraint: FK(session_id) REFERENCES db_sessions(id) ON DELETE CASCADE
  - constraint: tool_name IN ('execute_query','show_tables','describe_table')
  - constraint: operation_kind IN ('select','insert','update','delete','ddl','transaction','other','introspection')
- `operation_results.json` — Stores result payloads for operations (rows/columns for SELECT, list of tables for show_tables, column metadata for describe_table). Separated from sql_operations to keep the audit log small and allow truncation/retention policies. (18 rows; fields: ['id', 'operation_id', 'result_format', 'payload', 'truncated', 'byte_size', 'created_at', 'updated_at'])
  - lifecycle `result_format`: ['json_rows', 'json_schema', 'text', 'none']
  - constraint: required(operation_id, result_format, truncated, byte_size)
  - constraint: unique(operation_id)
  - constraint: FK(operation_id) REFERENCES sql_operations(id) ON DELETE CASCADE
  - constraint: result_format IN ('json_rows','json_schema','text','none')
- `secrets.json` — Encrypted secret storage for database passwords. Raw passwords from connect_database are never stored in plaintext; they are wrapped and referenced by db_connections.password_secret_id. (18 rows; fields: ['id', 'secret_type', 'ciphertext', 'key_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'rotated', 'revoked']
  - constraint: required(secret_type, ciphertext, key_id, status)
  - constraint: secret_type IN ('mysql_password')
  - constraint: status IN ('active','rotated','revoked')
  - constraint: ciphertext != ''

## Business rules enforced by the tools

- connect_database(host, port, user, password, database) must create or reuse a db_connections row matching (host, port, username, database_name) and store the password in secrets, then create exactly one db_sessions row with status transitioning connecting -> connected on success or -> error on failure.
- execute_query(query) must only run when there exists a most-recent db_sessions record for the caller in status='connected'; it must create a sql_operations row with tool_name='execute_query' and query_text=query, then transition status queued->running->(succeeded|failed).
- show_tables() must only run on a connected session and must create a sql_operations row with tool_name='show_tables' and operation_kind='introspection'.
- describe_table(table_name) must only run on a connected session; it must create a sql_operations row with tool_name='describe_table' and table_name=provided value; table_name must match the MySQL identifier pattern /^[A-Za-z0-9_]+$/ or be rejected.
- disconnect_database() must transition the current connected session to disconnecting then disconnected; after disconnected, no further sql_operations may be created for that session.
- For every sql_operations row with status='succeeded', an operation_results row must exist (result_format may be 'none' for statements with no result set). For status in ('failed','cancelled'), operation_results may be omitted or stored with result_format='none'.
- operation_results.payload must be truncated and truncated=true when byte_size would exceed 10MB; the system must still store rows_returned/rows_affected on sql_operations.
- Passwords provided to connect_database must never be persisted outside secrets.ciphertext; db_connections must only reference secrets via password_secret_id.
- A db_connections row in status='disabled' must not be used to create new db_sessions; existing sessions remain valid until disconnected.