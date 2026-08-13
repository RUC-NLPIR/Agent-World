# PostgreSQL MCP Server — local MCP environment

This backend powers a PostgreSQL MCP server that executes ad-hoc SQL and exposes database introspection (schemas, tables, columns, and foreign keys) as tools. The main workflows are (1) running SQL statements as query jobs and storing results/audit trails and (2) caching catalog metadata to answer list/describe/relationship tools efficiently with proper access controls.

Repository: https://github.com/gldc/mcp-postgres
Homepage: https://smithery.ai/server/@gldc/mcp-postgres

## Datastore

- `projects.json` — A logical database target (one PostgreSQL instance/dbname) that the MCP server can connect to. Used to scope metadata caching and query execution auditing. (12 rows; fields: ['id', 'name', 'host', 'port', 'database_name', 'ssl_mode', 'allowed_schemas', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(name)
  - constraint: port >= 1 AND port <= 65535
  - constraint: database_name <> ''
  - constraint: host <> ''
- `api_keys.json` — API keys used by MCP clients to authenticate and authorize access to a configured project, including basic quota/rate controls suitable for a small MCP server. (12 rows; fields: ['id', 'project_id', 'name', 'key_hash', 'status', 'permissions', 'max_queries_per_minute', 'max_rows_per_query', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(project_id, name)
  - constraint: unique(key_hash)
  - constraint: max_queries_per_minute IS NULL OR max_queries_per_minute > 0
  - constraint: max_rows_per_query IS NULL OR (max_rows_per_query >= 1 AND max_rows_per_query <= 100000)
- `catalog_objects.json` — Cached PostgreSQL catalog metadata for schemas, tables, views, materialized views, and columns. Supports list_schemas, list_tables, describe_table, and relationship discovery without repeatedly scanning pg_catalog. (30 rows; fields: ['id', 'project_id', 'schema_name', 'object_type', 'object_name', 'parent_object_id', 'ordinal_position', 'data_type', 'is_nullable', 'column_default', 'comment', 'status', 'source_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'dropped']
  - constraint: unique(project_id, object_type, schema_name, object_name, parent_object_id)
  - constraint: ordinal_position IS NULL OR ordinal_position >= 1
  - constraint: object_type = 'column' implies parent_object_id IS NOT NULL
  - constraint: object_type IN ('table','view','materialized_view') implies parent_object_id IS NULL
- `foreign_keys.json` — Cached explicit foreign key constraints between tables, as discovered from pg_constraint/pg_catalog. Drives get_foreign_keys and the explicit portion of find_relationships. (30 rows; fields: ['id', 'project_id', 'schema_name', 'table_name', 'constraint_name', 'columns', 'referenced_schema_name', 'referenced_table_name', 'referenced_columns', 'on_update', 'on_delete', 'is_deferrable', 'initially_deferred', 'status', 'source_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'dropped']
  - constraint: unique(project_id, schema_name, table_name, constraint_name)
  - constraint: array_length(columns) = array_length(referenced_columns)
  - constraint: array_length(columns) >= 1
- `query_jobs.json` — Audited SQL executions initiated via the MCP query tool, including request context, execution status, timing, and truncated results/error info. (28 rows; fields: ['id', 'project_id', 'api_key_id', 'schema_name', 'sql_text', 'statement_type', 'status', 'started_at', 'finished_at', 'duration_ms', 'row_count', 'result_format', 'result_rows', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: row_count IS NULL OR row_count >= 0
  - constraint: result_format = 'none' implies result_rows IS NULL
  - constraint: status IN ('succeeded','failed','cancelled') implies finished_at IS NOT NULL

## Business rules enforced by the tools

- All tool calls must be authorized by an active api_keys record scoped to an active projects record, unless the server is running in an explicitly configured no-auth mode (in which case api_key_id may be NULL but project_id must still resolve).
- list_schemas returns distinct schema_name from catalog_objects where object_type='schema', project_id matches, status='present', and (projects.allowed_schemas is NULL OR schema_name IN allowed_schemas).
- list_tables defaults to schema_name='public' when the caller provides no schema; it returns catalog_objects with object_type IN ('table','view','materialized_view'), schema_name match, status='present', filtered by allowed_schemas.
- describe_table defaults to schema_name='public' when not provided; it returns the table/view object plus its child column records (object_type='column', parent_object_id=table_object.id) ordered by ordinal_position.
- get_foreign_keys defaults to schema_name='public' when not provided; it returns foreign_keys rows for (project_id, schema_name, table_name) where status='present'.
- find_relationships returns (a) explicit relationships from foreign_keys for the table as both referencing and referenced target within the same project and (b) implied relationships where a column name matches a referenced table primary key naming convention (e.g., *_id) only if both tables/columns exist in catalog_objects with status='present' and within allowed_schemas.
- query tool creates a query_jobs row and must enforce api_keys.permissions.allow_query=true; if allow_write=false then statement_type must not be in ('insert','update','delete','ddl','transaction') and the SQL must be rejected/marked failed.
- query tool must enforce per-key rate limit max_queries_per_minute (or server default) by rejecting or delaying requests when exceeded, and must update api_keys.last_used_at on success or failure.
- query results persisted into query_jobs.result_rows must be truncated to api_keys.max_rows_per_query (or server default cap) and must not exceed a hard cap of 100000 rows.
- Catalog caches (catalog_objects, foreign_keys) may be refreshed asynchronously, but refresh operations must be idempotent: upserts must preserve uniqueness constraints and mark missing previously-present objects as status='dropped' with updated source_refreshed_at.