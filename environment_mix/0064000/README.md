# Datadog MCP Server — local MCP environment

This backend models a Datadog MCP gateway that stores connection credentials, caches Datadog resources (monitors, dashboards, metrics metadata, incidents), and persists user search/analytics queries over events and logs with their result snapshots. Primary workflows are: authenticate a workspace to Datadog, sync/browse core objects, and execute event/log queries while enforcing rate limits and retaining query history for observability/auditing.

Repository: https://github.com/GeLi2001/datadog-mcp-server
Homepage: https://smithery.ai/server/@GeLi2001/datadog-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace boundary for the MCP server. Holds Datadog org context, connection status, and retention defaults used by query/result storage. (12 rows; fields: ['id', 'name', 'datadog_site', 'datadog_org_name', 'datadog_org_id', 'default_result_limit', 'result_retention_days', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(name)
  - constraint: default_result_limit between 1 and 1000
  - constraint: result_retention_days between 1 and 365
  - constraint: last_sync_at is null or last_sync_at <= now()
- `api_credentials.json` — Datadog API credentials per workspace. Stores encrypted keys and enforces single active credential set per workspace. (12 rows; fields: ['id', 'workspace_id', 'auth_type', 'api_key_ciphertext', 'app_key_ciphertext', 'key_fingerprint', 'status', 'last_validated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'rotating', 'revoked']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id) where status = 'active'
  - constraint: unique(key_fingerprint, workspace_id)
  - constraint: last_validated_at is null or last_validated_at <= now()
- `datadog_assets.json` — Cache of Datadog objects needed by browse-style tools: monitors, dashboards, metrics index entries, metric metadata, incidents, and events (optional). This provides fast reads and allows tooling to work even when Datadog is rate-limiting. (18 rows; fields: ['id', 'workspace_id', 'asset_type', 'external_id', 'title', 'tags', 'state', 'attributes', 'source_updated_at', 'cached_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `asset_type`: ['monitor', 'dashboard', 'metric', 'metric_metadata', 'incident', 'event']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, asset_type, external_id)
  - constraint: cached_at <= now()
  - constraint: expires_at is null or expires_at >= cached_at
- `query_jobs.json` — Persisted executions of read/search tools (events/logs queries and log aggregations). Stores request parameters, time ranges, sorting, and status for auditing, retries, and rate limiting. (18 rows; fields: ['id', 'workspace_id', 'tool_name', 'request_params', 'filter_query', 'from_time', 'to_time', 'sort', 'limit', 'group_states', 'tags', 'monitor_tags', 'aggregation', 'status', 'error_message', 'datadog_request_id', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: limit is null or limit between 1 and 1000
  - constraint: started_at is null or started_at <= now()
  - constraint: finished_at is null or (started_at is not null and finished_at >= started_at)
- `query_results.json` — Stored snapshots of responses for query jobs, including lists of monitors/dashboards/metrics and log/event search results. Enables pagination-like followups by reusing stored results and supports auditing. (18 rows; fields: ['id', 'query_job_id', 'workspace_id', 'result_kind', 'items', 'item', 'count', 'next_cursor', 'response_meta', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `result_kind`: ['monitors', 'monitor', 'dashboards', 'dashboard', 'metrics', 'metric_metadata', 'events', 'incidents', 'logs_search', 'logs_aggregate']
  - constraint: fk(query_job_id) references query_jobs(id) on delete cascade
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(query_job_id)
  - constraint: count is null or count >= 0

## Business rules enforced by the tools

- All tool executions MUST be scoped to exactly one workspace; the implementation determines the workspace from server configuration or session context (since tool parameters are empty).
- A workspace with status != 'active' MUST NOT execute tools that call Datadog; such calls must fail with an actionable error and create a query_job with status='failed'.
- Exactly one api_credentials row per workspace may have status='active' at any time; rotating credentials may exist concurrently but cannot be used unless promoted to active.
- For get-monitors/get-monitor, any groupStates filter must be normalized to internal state values: 'no data' -> 'no_data'; unknown states must be rejected.
- For get-events, search-logs, and aggregate-logs, from_time and to_time MUST be provided by the server defaults if missing from the tool request; the resolved window MUST NOT exceed 31 days.
- For search-logs and aggregate-logs, limit MUST default to workspaces.default_result_limit when not provided and MUST be capped at 1000.
- Each tool invocation MUST create a query_jobs row; on success it MUST write exactly one query_results row linked by query_job_id.
- Cached datadog_assets entries MUST be upserted by (workspace_id, asset_type, external_id) and their cached_at must update on every refresh.
- Cache TTL enforcement: datadog_assets.expires_at and query_results.expires_at MUST be set based on workspaces.result_retention_days (or a stricter per-type TTL), and background cleanup MUST delete expired rows.
- FK integrity MUST be enforced: deleting a workspace must cascade-delete api_credentials, datadog_assets, query_jobs, and query_results.
- Status transitions MUST be enforced exactly as specified in each lifecycle.transitions map; direct jumps (e.g., queued -> succeeded) are invalid.
- For aggregate-logs, query_jobs.aggregation MUST include at least one compute/measure definition in order to execute; otherwise the job must fail validation.