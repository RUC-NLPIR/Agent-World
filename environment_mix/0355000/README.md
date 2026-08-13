# E2B — local MCP environment

This backend stores users, API keys, and ephemeral code execution sandboxes created via the E2B API. The primary workflow is authenticating a caller with an API key, provisioning a sandbox, tracking its lifecycle and resource usage, and persisting execution events for debugging, auditing, and quota enforcement.

Repository: https://github.com/e2b-dev/mcp-server
Homepage: https://smithery.ai/server/e2b

## Datastore

- `workspaces.json` — Tenant/workspace boundary for API usage, billing/quota, and sandbox isolation. (12 rows; fields: ['id', 'name', 'plan', 'status', 'quota_sandboxes_per_minute', 'quota_concurrent_sandboxes', 'quota_cpu_ms_per_day', 'quota_memory_mb_s_per_day', 'quota_network_egress_mb_per_day', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: quota_sandboxes_per_minute >= 0
  - constraint: quota_concurrent_sandboxes >= 0
  - constraint: quota_cpu_ms_per_day >= 0
- `api_keys.json` — API keys used to authenticate requests to run code and provision sandboxes. (19 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'prefix', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(prefix)
  - constraint: key_hash length >= 32
- `sandboxes.json` — Ephemeral compute environments created to execute user code (the core unit behind run_code). (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'runtime', 'region', 'image', 'cpu_millicores', 'memory_mb', 'ttl_seconds', 'started_at', 'terminated_at', 'last_heartbeat_at', 'exit_code', 'failure_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'running', 'terminated', 'failed', 'expired']
  - constraint: cpu_millicores between 50 and 16000
  - constraint: memory_mb between 64 and 65536
  - constraint: ttl_seconds between 10 and 86400
  - constraint: terminated_at is null when status in ('provisioning','running')
- `executions.json` — A single run_code invocation, including request/response metadata and aggregated usage for quota and auditing. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'sandbox_id', 'status', 'request_payload', 'response_payload', 'error', 'duration_ms', 'cpu_ms', 'memory_mb_s', 'network_egress_mb', 'idempotency_key', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: cpu_ms >= 0
  - constraint: memory_mb_s >= 0
  - constraint: network_egress_mb >= 0
  - constraint: duration_ms is null when status in ('queued','running')
- `usage_ledger.json` — Daily per-workspace usage aggregation used to enforce quotas and support billing. (16 rows; fields: ['id', 'workspace_id', 'usage_date', 'sandboxes_created', 'cpu_ms', 'memory_mb_s', 'network_egress_mb', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'finalized']
  - constraint: unique(workspace_id, usage_date)
  - constraint: sandboxes_created >= 0
  - constraint: cpu_ms >= 0
  - constraint: memory_mb_s >= 0

## Business rules enforced by the tools

- run_code must authenticate using an active api_keys row; revoked keys are rejected.
- run_code must reject requests for workspaces with status != 'active'.
- For each run_code call, create an executions row with request_payload = {} and status transitions queued -> running -> (succeeded|failed|cancelled).
- If executions.idempotency_key is provided and a row already exists for (workspace_id, idempotency_key), the backend must return the existing response_payload and must not provision a new sandbox.
- A sandbox may be provisioned for an execution; sandboxes.status must follow declared transitions and sandboxes.terminated_at must be set when moving into (terminated|failed|expired).
- Before provisioning a new sandbox, enforce workspace quota_concurrent_sandboxes by counting sandboxes with status in ('provisioning','running') for the workspace.
- Before accepting run_code, enforce per-workspace rate limit quota_sandboxes_per_minute based on sandboxes.created_at within the last 60 seconds (or an equivalent token-bucket stored in a cache; if persisted, it must reconcile with these rows).
- On execution completion, executions.cpu_ms/memory_mb_s/network_egress_mb must be finalized and added to usage_ledger for the corresponding workspace and UTC day; ledger rows with status='finalized' must be immutable.
- If adding finalized usage would exceed any daily quota (quota_cpu_ms_per_day, quota_memory_mb_s_per_day, quota_network_egress_mb_per_day), subsequent run_code calls for that workspace must be rejected until the next day bucket.