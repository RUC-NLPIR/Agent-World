# Kagi — local MCP environment

This backend stores Kagi API tenants and credentials, plus a durable log of search requests and the corresponding result payloads returned to clients. The main workflow is: authenticate an API key, accept a search request, dispatch to the search engine, store the query and response for auditing/billing, and return results.

Repository: https://github.com/kagisearch/kagimcp
Homepage: https://smithery.ai/server/kagimcp

## Datastore

- `workspaces.json` — Tenant/workspace container for API usage, billing, and data retention policies. (12 rows; fields: ['id', 'name', 'status', 'plan', 'data_retention_days', 'monthly_request_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: data_retention_days between 0 and 3650
  - constraint: monthly_request_quota is null or monthly_request_quota >= 0
- `api_keys.json` — API keys used to authenticate requests and associate them to a workspace with specific permissions and quotas. (24 rows; fields: ['id', 'workspace_id', 'name', 'status', 'key_hash', 'last_used_at', 'allowed_tools', 'monthly_request_quota_override', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: monthly_request_quota_override is null or monthly_request_quota_override >= 0
- `search_queries.json` — Durable log of search tool invocations, including inputs (empty in this MCP surface) and execution metadata. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'tool_name', 'input', 'request_ip', 'user_agent', 'error_code', 'error_message', 'http_status', 'duration_ms', 'created_at', 'updated_at', 'completed_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: tool_name = 'search'
  - constraint: input must be a JSON object (for this tool surface, must equal {})
- `search_responses.json` — Stored response payload and extracted metadata for each search invocation. (18 rows; fields: ['id', 'query_id', 'status', 'upstream_provider', 'result_count', 'response_json', 'response_text', 'bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['stored', 'redacted', 'purged']
  - constraint: foreign key (query_id) references search_queries(id) on delete cascade
  - constraint: unique(query_id)
  - constraint: result_count is null or result_count >= 0
  - constraint: bytes is null or bytes >= 0
- `usage_ledger.json` — Append-only accounting entries for rate limiting, quota enforcement, and billing reconciliation per workspace and API key. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'query_id', 'event_type', 'units', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['search_request', 'search_success', 'search_failure']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: foreign key (query_id) references search_queries(id) on delete set null
  - constraint: units >= 0

## Business rules enforced by the tools

- A call to tool 'search' must authenticate exactly one active api_keys row whose workspace is in status='active'.
- For this MCP tool surface, the search input parameters object must be empty {}; any non-empty object is rejected as invalid_request.
- Each accepted search invocation must create one search_queries row with status in ('queued','running') and an initial usage_ledger row with event_type='search_request' and units=1.
- A search_queries row may only transition according to the declared lifecycle transitions; terminal states are succeeded/failed/cancelled.
- On success, exactly one search_responses row must exist per search_queries row (unique(query_id)), and the corresponding usage_ledger must eventually include event_type='search_success'.
- On failure, search_queries.error_code must be non-null, and usage_ledger must eventually include event_type='search_failure'.
- Quota enforcement: for each workspace and API key, the number of usage_ledger events with event_type='search_request' in the current calendar month must not exceed monthly_request_quota_override if set, else workspaces.monthly_request_quota if set, else the plan default.
- Data retention enforcement: any search_queries/search_responses/usage_ledger rows older than workspaces.data_retention_days may be purged; purging a response must set search_responses.status='purged' and null out response_json/response_text.