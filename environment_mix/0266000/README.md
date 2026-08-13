# Dune Analytics — local MCP environment

This backend stores Dune Analytics query definitions, their executions, and the resulting datasets that can be fetched as the latest result. The main workflows are: triggering an execution of a stored Dune query (run_query), and retrieving the most recent successful result set for a query as a CSV payload (get_latest_result).

Repository: https://github.com/kukapay/dune-analytics-mcp
Homepage: https://smithery.ai/server/@kukapay/dune-analytics-mcp

## Datastore

- `api_keys.json` — API credentials/config used by this service to authenticate to Dune Analytics and to authorize callers of this MCP service. Even though the tool surface has no explicit parameters, production deployments typically require key management and rotation. (12 rows; fields: ['id', 'provider', 'name', 'key_hash', 'last4', 'status', 'scopes', 'rate_limit_per_minute', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(provider, name)
  - constraint: unique(provider, key_hash)
  - constraint: length(last4) = 4
  - constraint: rate_limit_per_minute >= 1 AND rate_limit_per_minute <= 6000
- `queries.json` — Catalog of Dune queries known to this service. Each query maps to a Dune query ID; executions and results reference this table. This supports run_query by providing a stable internal handle and metadata for execution. (18 rows; fields: ['id', 'dune_query_id', 'name', 'description', 'owner_key_id', 'status', 'default_output_format', 'cache_ttl_seconds', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(dune_query_id)
  - constraint: cache_ttl_seconds >= 0 AND cache_ttl_seconds <= 86400
  - constraint: status = 'deleted' implies deleted_at IS NOT NULL
- `query_executions.json` — Individual execution attempts of a Dune query (a run). run_query creates a new execution row (or reuses a cached latest successful execution depending on TTL), and get_latest_result reads the most recent successful execution for a query. (17 rows; fields: ['id', 'query_id', 'requested_by_key_id', 'provider_key_id', 'status', 'upstream_execution_id', 'started_at', 'finished_at', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: FK(query_id) REFERENCES queries(id) ON DELETE RESTRICT
  - constraint: duration_ms IS NULL OR (duration_ms >= 0 AND duration_ms <= 86400000)
  - constraint: status IN ('succeeded','failed','cancelled') implies finished_at IS NOT NULL
  - constraint: status = 'failed' implies error_message IS NOT NULL
- `query_results.json` — Materialized results for a specific execution, stored as CSV text payload for direct return by the tools. get_latest_result returns the CSV from the most recent succeeded execution; run_query may insert a new row when execution completes. (18 rows; fields: ['id', 'execution_id', 'query_id', 'format', 'csv_text', 'row_count', 'byte_size', 'checksum_sha256', 'generated_at', 'created_at', 'updated_at'])
  - constraint: unique(execution_id)
  - constraint: FK(execution_id) REFERENCES query_executions(id) ON DELETE CASCADE
  - constraint: FK(query_id) REFERENCES queries(id) ON DELETE RESTRICT
  - constraint: byte_size >= 0 AND byte_size <= 52428800

## Business rules enforced by the tools

- run_query must create a query_executions row with status='queued' (then 'running' and terminal state) for a specific queries record; if no queries row exists for the intended upstream Dune query ID, the service must create it or reject the run.
- get_latest_result must return the csv_text from the newest query_results whose execution is in status='succeeded' for a given query context; if none exist, it must return a not-found/empty-result error.
- A query in status='disabled' or 'deleted' cannot be executed by run_query; attempts must be rejected.
- A query_executions row may transition only according to the declared lifecycle transitions; terminal states are immutable.
- query_results may only be inserted for an execution whose status is 'succeeded'; inserting results for non-succeeded executions must be rejected.
- If queries.cache_ttl_seconds > 0, run_query should return the most recent succeeded result without creating a new execution when generated_at is within TTL; otherwise it must create a new execution.
- Per api_keys.rate_limit_per_minute, the service must reject calls that exceed the limit for the calling key; revoked keys cannot access either tool.
- Result payload limits must be enforced: byte_size must not exceed 50MB and csv_text length must correspond to byte_size.