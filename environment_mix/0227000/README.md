# Snowflake Database Access Server — local MCP environment

This backend powers an API service that executes SQL against Snowflake and returns results to callers. It stores workspaces (Snowflake connection profiles), API keys for authentication/quotas, and an execution ledger of query runs including status, timing, errors, and result metadata for auditing and cost/usage control.

Repository: https://github.com/datawiz168/mcp-snowflake-service
Homepage: https://smithery.ai/server/@datawiz168/mcp-service-snowflake

## Datastore

- `workspaces.json` — Tenant/workspace records representing a Snowflake connection profile and configuration used for query execution. (12 rows; fields: ['id', 'name', 'status', 'snowflake_account', 'snowflake_region', 'default_warehouse', 'default_database', 'default_schema', 'auth_method', 'auth_secret_ref', 'network_policy', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: status in ('active','suspended','deleted')
  - constraint: auth_method in ('password','key_pair','oauth')
  - constraint: auth_secret_ref must be non-empty
- `api_keys.json` — API keys used by clients to call execute_query; supports revocation, scoping to a workspace, and quotas/rate limits. (12 rows; fields: ['id', 'workspace_id', 'key_hash', 'key_prefix', 'name', 'status', 'allowed_sql_types', 'max_rows', 'max_runtime_ms', 'rate_limit_per_minute', 'monthly_query_limit', 'monthly_credits_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (workspace_id) references workspaces(id)
  - constraint: unique(workspace_id, key_prefix)
  - constraint: status in ('active','revoked')
  - constraint: max_rows between 1 and 1000000
- `query_runs.json` — A durable ledger of each call to execute_query, including request metadata, execution status, Snowflake identifiers, and high-level results. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'submitted_sql', 'sql_statement_type', 'request_context', 'snowflake_query_id', 'started_at', 'finished_at', 'duration_ms', 'rows_returned', 'bytes_scanned', 'credits_attributed', 'error_code', 'error_message', 'result_format', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (workspace_id) references workspaces(id)
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: status in ('queued','running','succeeded','failed','cancelled')
  - constraint: duration_ms is null or duration_ms >= 0
- `query_result_chunks.json` — Optional persisted result sets for query runs (when results are too large to return inline or need auditing). Stored as JSON chunks or references to object storage. (19 rows; fields: ['id', 'query_run_id', 'chunk_index', 'row_count', 'payload_json', 'external_uri', 'content_sha256', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'purged']
  - constraint: foreign key (query_run_id) references query_runs(id) on delete cascade
  - constraint: unique(query_run_id, chunk_index)
  - constraint: chunk_index >= 0
  - constraint: row_count >= 0
- `usage_counters.json` — Pre-aggregated usage counters for enforcing per-key rate limits and monthly quotas; updated transactionally with query_runs. (17 rows; fields: ['id', 'api_key_id', 'window_type', 'window_start', 'request_count', 'credits_total', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'sealed']
  - constraint: foreign key (api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: window_type in ('minute','month')
  - constraint: request_count >= 0

## Business rules enforced by the tools

- execute_query must authenticate using an active api_keys row (status='active') unless invoked by an internal trusted caller; revoked keys are always rejected.
- execute_query must only run against an active workspace (workspaces.status='active'); suspended/deleted workspaces are rejected.
- On each execute_query call, the service must create a query_runs row with status='queued' then transition to 'running' when submitted to Snowflake, and finally to one of 'succeeded'|'failed'|'cancelled'; no other status transitions are permitted.
- The service must classify submitted_sql into sql_statement_type and verify it is included in api_keys.allowed_sql_types before execution; otherwise the query_runs row is marked failed with an authorization error.
- For each api_key_id, the number of calls in the current minute must not exceed api_keys.rate_limit_per_minute; enforcement must be atomic with inserting query_runs (or must pessimistically reserve capacity).
- If api_keys.monthly_query_limit is set, the number of query_runs for that api_key_id with created_at within the current month must not exceed the limit; otherwise reject before execution.
- If api_keys.monthly_credits_limit is set, the running sum of usage_counters.credits_total for the current month plus the new run's estimated/attributed credits must not exceed the limit; otherwise reject or cancel the run before Snowflake execution.
- Rows returned must be capped at api_keys.max_rows; if the underlying query would exceed it, the service must apply a LIMIT (when safe) or stop fetching and mark the run failed with a policy error.
- Query runtime must be capped at api_keys.max_runtime_ms; if exceeded, the service must attempt to cancel the Snowflake query (using snowflake_query_id when available) and mark the run cancelled or failed.
- When query_runs.result_format='chunked', results must be persisted in query_result_chunks with unique (query_run_id, chunk_index) ordering; at least one chunk must exist for succeeded runs that return rows.
- query_result_chunks must store either payload_json or external_uri; purged chunks must not be returned to callers and should have payload_json/external_uri nulled or access revoked.
- Deleting a workspace is a soft delete (status='deleted'); it must not physically delete query_runs, but it must prevent new execute_query calls and should revoke/disable associated api_keys.