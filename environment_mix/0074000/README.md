# Perplexity Server — local MCP environment

This backend stores Perplexity question/answer sessions executed through a single MCP tool call. It tracks client workspaces, API credentials, individual ask requests, and the returned answers with citations, while enforcing basic lifecycle, idempotency, and quota/rate limits.

Repository: https://github.com/tanigami/mcp-server-perplexity
Homepage: https://smithery.ai/server/mcp-server-perplexity

## Datastore

- `workspaces.json` — Tenant boundary for MCP clients using the Perplexity Server; used for ownership, quota, and audit. (18 rows; fields: ['id', 'name', 'status', 'monthly_request_quota', 'monthly_token_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_request_quota >= 0
  - constraint: monthly_token_quota >= 0
- `api_keys.json` — API keys representing external MCP callers; used to authenticate and attribute usage to a workspace. (19 rows; fields: ['id', 'workspace_id', 'key_hash', 'label', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, key_hash)
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
- `perplexity_requests.json` — Each invocation of the ask_perplexity tool; stores input (even if empty), lifecycle, and linkage to the returned answer. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'input', 'idempotency_key', 'status', 'error_code', 'error_message', 'remote_request_id', 'latency_ms', 'estimated_tokens_in', 'estimated_tokens_out', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: unique(workspace_id, idempotency_key) where idempotency_key is not null
  - constraint: latency_ms is null or latency_ms >= 0
- `perplexity_answers.json` — Materialized result of a Perplexity request, including final text and structured metadata for citations and provider payload. (19 rows; fields: ['id', 'request_id', 'status', 'answer_text', 'citations', 'provider_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'final', 'error']
  - constraint: fk(request_id) references perplexity_requests(id) on delete cascade
  - constraint: unique(request_id)
  - constraint: citations is not null
  - constraint: provider_payload is not null
- `usage_ledger.json` — Append-only metering for quota enforcement and billing analytics at workspace and API key granularity. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'request_id', 'event_type', 'quantity', 'period_ym', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['request', 'tokens_in', 'tokens_out']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: fk(request_id) references perplexity_requests(id) on delete cascade
  - constraint: quantity >= 0

## Business rules enforced by the tools

- ask_perplexity creates exactly one perplexity_requests row with tool_name='ask_perplexity' and input={} (since the tool has no parameters).
- If an idempotency_key is provided by the caller, the system must return the existing request for (workspace_id, idempotency_key) instead of creating a duplicate.
- A perplexity_answers row must be created when a request enters status in ('succeeded','failed'); it must be status='final' for succeeded and status='error' for failed.
- Requests may only transition according to the defined lifecycle; once in a terminal state (succeeded/failed/cancelled) they cannot be modified except for non-semantic audit fields.
- On request completion, usage_ledger must contain exactly three entries for that request: event_type=request with quantity=1, tokens_in with quantity=estimated_tokens_in, tokens_out with quantity=estimated_tokens_out; each (request_id,event_type) is unique.
- A workspace in status='suspended' or 'deleted' cannot execute ask_perplexity; attempts must be rejected before creating a running request.
- For each workspace and period_ym, the sum of usage_ledger quantities for event_type='request' must not exceed workspaces.monthly_request_quota; likewise tokens_in+tokens_out must not exceed workspaces.monthly_token_quota. Requests that would exceed quota must be rejected or cancelled before calling the upstream provider.
- api_keys with status='revoked' cannot be used to create new requests; last_used_at is only updated on successful authenticated calls.