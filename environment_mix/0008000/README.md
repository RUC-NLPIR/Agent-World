# Metabase MCP — local MCP environment

This backend models a Metabase MCP server that connects to a Metabase instance, exposes read APIs for listing Metabase objects (databases, cards/questions, dashboards), and executes queries either by running a saved card or ad-hoc SQL against a selected Metabase database. It also stores execution/audit logs for query runs, including status and results metadata, to support observability, quotas, and troubleshooting.

Repository: https://github.com/hyeongjun-dev/metabase-mcp-server
Homepage: https://smithery.ai/server/@hyeongjun-dev/metabase-mcp-server

## Datastore

- `metabase_connections.json` — Configured remote Metabase instances that this MCP server can talk to (base URL + auth). In many deployments there will be exactly one active connection, but the model supports multiple for multi-tenant setups. (12 rows; fields: ['id', 'name', 'base_url', 'auth_type', 'username', 'password_secret_ref', 'api_key_secret_ref', 'status', 'last_healthcheck_at', 'last_healthcheck_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(base_url)
  - constraint: auth_type = 'session' implies username is not null and password_secret_ref is not null
  - constraint: auth_type = 'api_key' implies api_key_secret_ref is not null
- `metabase_databases.json` — Snapshot of databases visible in the connected Metabase instance. Used to serve list_databases and to validate execute_query targets. (12 rows; fields: ['id', 'connection_id', 'metabase_database_id', 'name', 'engine', 'is_sample', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'unavailable']
  - constraint: unique(connection_id, metabase_database_id)
  - constraint: metabase_database_id > 0
- `metabase_cards.json` — Snapshot of Metabase cards/questions. Used to serve list_cards and to validate/execute execute_card, as well as to map cards into dashboards. (38 rows; fields: ['id', 'connection_id', 'metabase_card_id', 'name', 'description', 'database_id', 'dataset_query', 'query_type', 'archived', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted_remote']
  - constraint: unique(connection_id, metabase_card_id)
  - constraint: metabase_card_id > 0
  - constraint: archived = true implies status != 'active'
- `metabase_dashboards.json` — Snapshot of Metabase dashboards. Used to serve list_dashboards and to retrieve dashboard composition via get_dashboard_cards. (12 rows; fields: ['id', 'connection_id', 'metabase_dashboard_id', 'name', 'description', 'archived', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted_remote']
  - constraint: unique(connection_id, metabase_dashboard_id)
  - constraint: metabase_dashboard_id > 0
  - constraint: archived = true implies status != 'active'
- `dashboard_cards.json` — Join table representing which cards are placed on which dashboards, including layout metadata. Used to serve get_dashboard_cards. (35 rows; fields: ['id', 'connection_id', 'dashboard_id', 'card_id', 'metabase_dashboardcard_id', 'position', 'visualization_settings', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(dashboard_id, card_id)
  - constraint: position >= 0
  - constraint: metabase_dashboardcard_id is null or metabase_dashboardcard_id > 0
  - constraint: connection_id must equal (select connection_id from metabase_dashboards where id = dashboard_id)
- `query_executions.json` — Audit log of executions initiated through MCP tools execute_query and execute_card, including timing, status, and truncated results metadata. (20 rows; fields: ['id', 'connection_id', 'execution_type', 'metabase_database_id', 'database_id', 'metabase_card_id', 'card_id', 'native_sql', 'parameters', 'status', 'started_at', 'finished_at', 'duration_ms', 'row_count', 'result_columns', 'result_preview_rows', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: execution_type = 'native_sql' implies metabase_database_id is not null and native_sql is not null
  - constraint: execution_type = 'card' implies metabase_card_id is not null
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: row_count is null or row_count >= 0

## Business rules enforced by the tools

- list_dashboards returns metabase_dashboards where connection_id is active and status in ('active','archived'); records with status='deleted_remote' must be excluded.
- list_cards returns metabase_cards where connection_id is active and status in ('active','archived'); records with status='deleted_remote' must be excluded.
- list_databases returns metabase_databases where connection_id is active and status='active' by default; optionally include archived/unavailable only for admins (if such a concept exists in the deployment).
- get_dashboard_cards requires a resolvable dashboard (metabase_dashboards.status != 'deleted_remote'); it returns dashboard_cards rows with status='active' joined to metabase_cards (excluding cards with status='deleted_remote').
- execute_card must create a query_executions row with execution_type='card' and metabase_card_id set; if the card is known locally, card_id must be set and connection_id must match the card's connection_id.
- execute_query must create a query_executions row with execution_type='native_sql' and metabase_database_id + native_sql set; if the database is known locally, database_id must be set and connection_id must match the database's connection_id.
- All execution requests must be rejected when metabase_connections.status != 'active'.
- A query_executions row may transition status only according to its lifecycle transitions; implementations must not allow reverting from terminal states (succeeded/failed/cancelled).
- When status becomes 'succeeded' or 'failed' or 'cancelled', finished_at must be set and duration_ms must be computed as (finished_at-started_at) in milliseconds (non-negative).
- Data synchronization jobs (out of scope of the tool surface) may upsert metabase_databases/metabase_cards/metabase_dashboards/dashboard_cards by (connection_id, metabase_*_id) uniqueness; deletions in Metabase must be represented as status='deleted_remote' rather than hard delete to preserve FK integrity and execution audit trails.