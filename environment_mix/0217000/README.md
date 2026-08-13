# Jina AI — local MCP environment

This backend powers a thin API gateway over Jina AI capabilities for web reading, web search, and grounding-based fact checking. It stores tenants and API keys, logs each tool invocation as a request with inputs/outputs, and enforces per-tenant quotas plus lifecycle/status transitions for async/failed requests.

Repository: https://github.com/joeBlockchain/mcp-jina-ai
Homepage: https://smithery.ai/server/jina-ai-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace accounts that own API keys, quotas, and all tool requests. (18 rows; fields: ['id', 'name', 'plan', 'status', 'default_region', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: name length between 1 and 120
  - constraint: plan in (free, pro, enterprise)
- `api_keys.json` — API keys used to authenticate callers to this service; scoped to a workspace and used for quota accounting. (19 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_prefix)
  - constraint: key_prefix length between 6 and 24
- `quota_buckets.json` — Per-workspace rolling quota limits and current usage counters for tool calls and upstream cost control. (18 rows; fields: ['id', 'workspace_id', 'period', 'period_start', 'period_end', 'max_requests', 'used_requests', 'max_upstream_cost_usd_micros', 'used_upstream_cost_usd_micros', 'created_at', 'updated_at'])
  - constraint: foreign key(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, period, period_start)
  - constraint: period_end > period_start
  - constraint: max_requests >= 0
- `tool_requests.json` — Normalized log of every tool invocation (read_webpage, search_web, fact_check), including inputs, outputs, timing, and errors. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'input', 'output', 'error', 'idempotency_key', 'client_ip', 'user_agent', 'upstream_provider', 'upstream_endpoint', 'upstream_request_id', 'upstream_latency_ms', 'total_latency_ms', 'upstream_cost_usd_micros', 'created_at', 'updated_at', 'started_at', 'completed_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: upstream_cost_usd_micros >= 0
  - constraint: upstream_latency_ms is null or upstream_latency_ms >= 0
- `web_artifacts.json` — Cached canonical artifacts produced by read_webpage/search_web/fact_check such as fetched pages, extracted text, and search result snippets, linked back to the originating request. (19 rows; fields: ['id', 'workspace_id', 'tool_request_id', 'artifact_type', 'source_url', 'title', 'content_text', 'content_html', 'snippet', 'metadata', 'content_sha256', 'expires_at', 'created_at', 'updated_at'])
  - constraint: foreign key(workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key(tool_request_id) references tool_requests(id) on delete cascade
  - constraint: metadata must be a JSON object (not array/scalar)
  - constraint: expires_at is null or expires_at > created_at

## Business rules enforced by the tools

- Every invocation of read_webpage, search_web, or fact_check MUST create exactly one tool_requests row with tool_name set accordingly; tool_requests.input MUST store the raw request body (even though the published schema is empty).
- A workspace in status=suspended or status=closed MUST be rejected from executing any tool; attempts may still be logged as tool_requests with status=failed and error.code='workspace_inactive'.
- Authentication MUST resolve an api_keys row by key_prefix then verify key_hash; on success api_keys.last_used_at MUST be updated and tool_requests.api_key_id MUST be set.
- Before transitioning a tool request from queued->running, the service MUST check quota_buckets for the workspace and current time window and enforce: used_requests + 1 <= max_requests and used_upstream_cost_usd_micros + estimated_cost <= max_upstream_cost_usd_micros; otherwise the request MUST fail with error.code='quota_exceeded'.
- On completion of a request (succeeded/failed/cancelled), quota usage MUST be accounted exactly once by incrementing used_requests and adding upstream_cost_usd_micros (0 allowed). Idempotent retries with the same (workspace_id, api_key_id, tool_name, idempotency_key) MUST return the original tool_requests row and MUST NOT double-charge quota.
- tool_requests.status transitions MUST follow the declared transition map; output MUST be non-null only for status=succeeded; error MUST be non-null only for status=failed.
- read_webpage MUST be able to persist a webpage artifact (web_artifacts.artifact_type='webpage') containing at least one of content_text or content_html; search_web MUST be able to persist 0..N web_artifacts rows of artifact_type='search_result'; fact_check MUST be able to persist 0..N web_artifacts rows of artifact_type='fact_check_evidence'.
- Foreign key integrity MUST be enforced: a tool_requests row cannot reference an api_key_id from a different workspace; a web_artifacts row cannot reference a tool_request_id from a different workspace.