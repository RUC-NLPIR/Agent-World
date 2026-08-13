# PostgreSQL Database Management Server — local MCP environment

This backend stores managed PostgreSQL connection profiles and a full audit trail of administrative actions executed through the API (analysis/debug, schema changes, query execution, user/permission changes, and data movement). The main workflows are: register/resolve a connection (by connection string), execute an operation tool which creates an operation record, and optionally track long-running import/export/copy jobs with their parameters and results/metrics.

Repository: https://github.com/HenkDz/postgresql-mcp-server
Homepage: https://smithery.ai/server/@HenkDz/postgresql-mcp-server

## Datastore

- `pg_connections.json` — Registered PostgreSQL connection profiles used by tools when a connectionString is supplied or resolved from environment/CLI defaults. Stores sanitized connection identity and optional encrypted secret material (implementation-dependent). (27 rows; fields: ['id', 'display_name', 'connection_string_redacted', 'connection_string_secret_ref', 'host', 'port', 'database_name', 'username', 'ssl_mode', 'status', 'last_tested_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(connection_string_redacted)
  - constraint: port is null or (port >= 1 and port <= 65535)
- `pg_operations.json` — Immutable audit log of every tool invocation (read, mutate, admin, and monitoring). Captures the exact tool name, normalized parameters, execution timing, and high-level outcome. (38 rows; fields: ['id', 'tool_name', 'connection_id', 'source_connection_id', 'target_connection_id', 'operation_group', 'requested_operation', 'params', 'params_hash', 'status', 'started_at', 'finished_at', 'duration_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: finished_at is null or started_at is not null
  - constraint: status in ('queued','running') implies finished_at is null
  - constraint: tool_name='pg_copy_between_databases' implies source_connection_id is not null and target_connection_id is not null
- `pg_operation_results.json` — Structured results for operations (plans, rows, diagnostics, monitoring snapshots). Large payloads may be stored externally and referenced here. (38 rows; fields: ['id', 'operation_id', 'result_type', 'content_format', 'content_json', 'content_text', 'external_blob_ref', 'rows_returned', 'rows_affected', 'warnings', 'created_at', 'updated_at'])
  - lifecycle `result_type`: ['analysis_report', 'debug_report', 'schema_info', 'execution_rows', 'execution_summary', 'explain_plan', 'stats_report', 'monitor_snapshot', 'comments_dump']
  - constraint: unique(operation_id, result_type)
  - constraint: rows_returned is null or rows_returned >= 0
  - constraint: rows_affected is null or rows_affected >= 0
  - constraint: content_json is not null or content_text is not null or external_blob_ref is not null
- `pg_data_transfer_jobs.json` — Tracks long-running table-level data movement jobs: export, import, and copy between databases. Stores paths, formats, and progress for observability and retries. (38 rows; fields: ['id', 'operation_id', 'job_type', 'source_connection_id', 'target_connection_id', 'schema', 'table_name', 'where_clause', 'limit', 'format', 'delimiter', 'output_path', 'input_path', 'truncate_first', 'truncate_target', 'status', 'started_at', 'finished_at', 'rows_processed', 'bytes_processed', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(operation_id)
  - constraint: limit is null or limit > 0
  - constraint: rows_processed is null or rows_processed >= 0
  - constraint: bytes_processed is null or bytes_processed >= 0
- `pg_object_metadata_cache.json` — Optional cache of discovered database objects and comments to accelerate bulk_get/get_info style requests and to provide historical visibility even if objects later change. Populated by schema/comment tools and monitoring. (35 rows; fields: ['id', 'connection_id', 'schema', 'object_type', 'object_name', 'object_identity', 'definition', 'comment', 'attributes', 'observed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'stale', 'deleted']
  - constraint: unique(connection_id, object_identity)
  - constraint: attributes must be an object (not null)

## Business rules enforced by the tools

- Every tool invocation MUST create exactly one pg_operations row with tool_name equal to the invoked tool and params containing all validated request parameters (including defaults applied), with secrets redacted (e.g., pg_manage_users.password must not be stored in plaintext).
- If a connectionString (or sourceConnectionString/targetConnectionString) is provided, the server MUST resolve it to a pg_connections row (creating one if allowed) and attach connection_id/source_connection_id/target_connection_id accordingly; resolution uses connection_string_redacted as a uniqueness key.
- pg_analyze_database MUST set pg_operations.requested_operation = analysisType and operation_group='analysis'.
- pg_debug_database MUST set pg_operations.requested_operation = issue and operation_group='debug'; params.logLevel default must be applied to params when omitted.
- All tools that accept schema/tableName/indexName/functionName/triggerName/constraintName/policyName MUST persist them inside pg_operations.params so that audit/history can reproduce the intent even if the object later changes.
- pg_execute_query/pg_execute_sql/pg_manage_query(explain) MUST persist the query/sql text in pg_operations.params and record produced output in pg_operation_results; EXPLAIN output format must match params.format.
- pg_execute_query.limit, pg_manage_query.limit, and pg_execute_query.timeout/pg_execute_sql.timeout MUST be validated as positive numbers when provided; effective server-side safety limits may further clamp these values and must emit a warning in pg_operation_results.warnings when clamping occurs.
- pg_export_table_data MUST create a pg_data_transfer_jobs row with job_type='export', output_path required, format defaulting to 'json' when omitted, and limit validated as integer > 0 when present.
- pg_import_table_data MUST create a pg_data_transfer_jobs row with job_type='import', input_path required, truncate_first default false, format default 'json'; if format='csv' and delimiter is omitted, the server must apply its CSV default and persist the effective delimiter in the job row.
- pg_copy_between_databases MUST create a pg_data_transfer_jobs row with job_type='copy', source_connection_id and target_connection_id required, truncate_target default false, and store where clause if provided.
- pg_monitor_database MUST validate alertThresholds ranges: connectionPercentage and deadTuplesPercentage in [0,100], cacheHitRatio in [0,1], and longRunningQuerySeconds/vacuumAge strictly > 0 when provided; effective thresholds must be stored in pg_operations.params.
- For mutating operations (schema changes, user/permission changes, comments set/remove, mutations, import/copy with truncate), pg_operations.operation_group MUST be one of ('schema','security','access','comments','sql','data_movement') and the system MUST record an execution_summary or schema_info/comments_dump result indicating what changed.
- pg_object_metadata_cache may be updated by get_info/get/get_policies/bulk_get calls; entries affected by a successful create/alter/drop operation MUST be marked stale (or updated) for the same connection_id and object_identity.