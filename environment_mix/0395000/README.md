# Datadog API Integration — local MCP environment

This backend stores Datadog tenant connections (API credentials/config) and cached representations of Datadog resources (incidents, monitors, dashboards, hosts, and downtimes) plus time-bounded query executions (metrics, logs, traces). The main workflows are: (1) connect a workspace to Datadog, (2) read/list resources either live or via cache, and (3) perform mutating actions (mute/unmute host, schedule/cancel downtime) with auditability and safe idempotency.

Repository: https://github.com/winor30/mcp-server-datadog
Homepage: https://smithery.ai/server/@winor30/mcp-server-datadog

## Datastore

- `workspaces.json` — Tenant/workspace boundary for a single Datadog integration deployment. All Datadog connections, cached resources, and query runs are scoped to a workspace. (12 rows; fields: ['id', 'name', 'status', 'default_datadog_connection_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_datadog_connection_id references datadog_connections.id and must belong to same workspace when set
- `datadog_connections.json` — Datadog API connection configuration per workspace (site/region + credentials). Tools use this to call Datadog and optionally to decide cache strategy. (12 rows; fields: ['id', 'workspace_id', 'name', 'site', 'api_key_hash', 'app_key_hash', 'status', 'last_verified_at', 'last_error', 'rate_limit_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(workspace_id, name)
  - constraint: workspace_id references workspaces.id
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
  - constraint: api_key_hash is required
- `dd_resources.json` — Materialized/cache view of Datadog domain objects needed by the tool surface: incidents, monitors, dashboards, hosts, and downtimes. A single table supports list/get operations and host state (mute). (35 rows; fields: ['id', 'workspace_id', 'connection_id', 'resource_type', 'datadog_id', 'name', 'status', 'tags', 'attributes', 'muted_until', 'last_seen_at', 'synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'muted', 'resolved', 'triggered', 'scheduled', 'cancelled', 'deleted', 'unknown']
  - constraint: workspace_id references workspaces.id
  - constraint: connection_id references datadog_connections.id
  - constraint: unique(workspace_id, resource_type, datadog_id)
  - constraint: if resource_type != 'host' then muted_until must be null
- `dd_query_runs.json` — Execution log and cached results for Datadog read/search operations that are time-bounded or potentially expensive: metrics, logs, traces, and derived aggregates like active hosts count. Supports replay/debugging, pagination tokens, and rate-limit governance. (36 rows; fields: ['id', 'workspace_id', 'connection_id', 'query_type', 'status', 'requested_at', 'started_at', 'finished_at', 'time_from', 'time_to', 'request', 'result', 'next_page_cursor', 'error', 'http_status', 'cost_units', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: workspace_id references workspaces.id
  - constraint: connection_id references datadog_connections.id
  - constraint: cost_units >= 0
  - constraint: http_status between 100 and 599 when not null
- `dd_mutation_jobs.json` — Durable audit + idempotency for Datadog mutating actions: mute_host, unmute_host, schedule_downtime, cancel_downtime. Each job captures desired change, ties it to a target resource, and records the Datadog response. (38 rows; fields: ['id', 'workspace_id', 'connection_id', 'action', 'status', 'idempotency_key', 'target_resource_id', 'target_datadog_id', 'request', 'result', 'http_status', 'error', 'requested_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: workspace_id references workspaces.id
  - constraint: connection_id references datadog_connections.id
  - constraint: http_status between 100 and 599 when not null
  - constraint: unique(workspace_id, idempotency_key)

## Business rules enforced by the tools

- All tool executions must be scoped to exactly one workspace and one active datadog_connections row; if the chosen connection status is not 'active', the tool must fail without calling Datadog.
- list_incidents reads dd_resources filtered by (resource_type='incident') ordered by updated_at desc; if cache is stale (synced_at older than a configured TTL), implementation may refresh from Datadog and upsert by unique(workspace_id, resource_type, datadog_id).
- get_incident reads dd_resources where resource_type='incident' and datadog_id matches the requested Datadog incident id; if not found, implementation must fetch from Datadog and upsert.
- get_monitors, list_dashboards, get_dashboard, list_hosts, list_downtimes are served from dd_resources with the corresponding resource_type; get_* requires a datadog_id match and must fetch+upsert when missing or stale.
- get_metrics, get_logs, list_traces, get_active_hosts_count must create a dd_query_runs row with status='queued' then progress status through valid transitions; on completion set finished_at and persist result or error.
- dd_query_runs must enforce time bounds for metrics/logs/traces: time_from and time_to are required and time_from < time_to; otherwise the run must be marked failed with a validation error and must not call Datadog.
- mute_host and unmute_host must create a dd_mutation_jobs row with a stable idempotency_key derived from (workspace_id, action, target_datadog_id, normalized request); retries must return the existing job result when status is succeeded or still running.
- On successful mute_host/unmute_host, the corresponding dd_resources host row (resource_type='host', datadog_id=host identifier) must be upserted/updated: status set to 'muted' or 'active', muted_until set appropriately, synced_at updated.
- schedule_downtime must create dd_mutation_jobs then upsert a dd_resources row of resource_type='downtime' using the Datadog returned downtime id as datadog_id; status must be 'scheduled' and synced_at updated.
- cancel_downtime must set dd_resources downtime status to 'cancelled' (or 'deleted' if Datadog returns not-found) only after dd_mutation_jobs succeeds; cancelling an already-cancelled downtime must be treated as idempotent success.
- Rate limiting: total outbound Datadog calls per connection must not exceed datadog_connections.rate_limit_per_minute; if exceeded, new dd_query_runs/dd_mutation_jobs must remain queued or be failed with a rate_limit error without calling Datadog.
- Data integrity: dd_resources.connection_id and dd_query_runs/ dd_mutation_jobs.connection_id must reference a connection in the same workspace; cross-workspace references are rejected.