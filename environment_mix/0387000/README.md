# InfluxDB MCP Server — local MCP environment

This backend models a minimal InfluxDB-like system behind an MCP server: organizations contain buckets, buckets store time-series points, and queries retrieve points from buckets. The primary workflows are: create an org, create a bucket within an org, write time-series data points into a bucket, and query stored points back out.

Repository: https://github.com/idoru/influxdb-mcp-server
Homepage: https://smithery.ai/server/@idoru/influxdb-mcp-server

## Datastore

- `orgs.json` — Tenant boundary for data isolation. Buckets, API tokens, and data retention policies are scoped to an organization. (12 rows; fields: ['id', 'name', 'status', 'default_retention_days', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_retention_days >= 0
  - constraint: default_retention_days <= 36500
- `buckets.json` — Storage namespace within an org. Time-series points are written into and queried from buckets. (20 rows; fields: ['id', 'org_id', 'name', 'description', 'retention_days', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(org_id, name)
  - constraint: retention_days >= 0
  - constraint: retention_days <= 36500
  - constraint: foreign_key(org_id) references orgs(id) on delete restrict
- `time_series_points.json` — Time-series data written into buckets. Each point represents a measurement at a timestamp with tags and fields, similar to InfluxDB line protocol semantics. (17 rows; fields: ['id', 'org_id', 'bucket_id', 'measurement', 'ts', 'tags', 'fields', 'ingest_source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['stored', 'expired']
  - constraint: foreign_key(org_id) references orgs(id) on delete restrict
  - constraint: foreign_key(bucket_id) references buckets(id) on delete restrict
  - constraint: bucket_org_consistency: bucket.org_id must equal time_series_points.org_id
  - constraint: measurement <> ''
- `mcp_tool_requests.json` — Audit and operational log of MCP tool invocations. Used to back the behavior of write-data/query-data/create-bucket/create-org even when tool parameters are empty (server may infer defaults from environment/session). (18 rows; fields: ['id', 'tool_name', 'request_payload', 'resolved_org_id', 'resolved_bucket_id', 'status', 'error_message', 'response_summary', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: request_payload is object (may be {})
  - constraint: foreign_key(resolved_org_id) references orgs(id) on delete set null
  - constraint: foreign_key(resolved_bucket_id) references buckets(id) on delete set null
  - constraint: finished_at >= started_at when both not null

## Business rules enforced by the tools

- create-org must insert a new orgs row with status='active' and unique name; if name is not provided by tool params (empty schema), the server must derive it from configuration and still satisfy uniqueness (e.g., auto-suffix).
- create-bucket must insert a buckets row tied to an existing active org; if org is not specified by tool params, resolved_org_id must be derived from server configuration/session and recorded in mcp_tool_requests.
- write-data must only write points into an active bucket whose org is active; each inserted time_series_points row must have org_id equal to the bucket's org_id and status='stored'.
- query-data must only return points from active buckets in active orgs and must not return points with status='expired'.
- A retention enforcement job (out of band) may transition time_series_points.status from 'stored' to 'expired' when ts is older than bucket.retention_days (or org default where applicable); expired points must never transition back to stored.
- Deleting an org or bucket is a soft-delete via status transition to 'deleted'; writes and queries against deleted entities must fail and be recorded as failed mcp_tool_requests.
- All tool invocations must be recorded in mcp_tool_requests with tool_name, request_payload (possibly {}), status transitions, and any resolved_org_id/resolved_bucket_id used to fulfill empty-parameter tool calls.