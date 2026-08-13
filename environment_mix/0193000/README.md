# Brave Search — local MCP environment

This backend powers a Brave Search integration that issues web and local search requests, records each search query, stores normalized result items, and tracks API credentials, quotas, and usage for billing/rate-limiting. Primary workflows are: accept a search request (web or local), execute it against Brave, persist the query + results, and enforce per-workspace API key validity and usage limits.

Repository: https://github.com/smithery-ai/reference-servers
Homepage: https://smithery.ai/server/@smithery-ai/brave-search

## Datastore

- `workspaces.json` — Tenant/workspace container for API consumers. Owns API keys, search queries, and usage limits. (12 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_request_quota', 'monthly_result_item_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_request_quota >= 0
  - constraint: monthly_result_item_quota >= 0
- `api_keys.json` — Stores Brave API credentials per workspace (hashed) and their operational status for request authentication and rotation. (12 rows; fields: ['id', 'workspace_id', 'provider', 'key_name', 'key_hash', 'last4', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(workspace_id, provider, key_name)
  - constraint: unique(workspace_id, provider, key_hash)
- `search_requests.json` — Represents an invocation of brave_web_search or brave_local_search, including execution metadata, response caching, and fallback handling. (35 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'query_text', 'local_intent', 'fallback_to_web', 'request_fingerprint', 'status', 'error_code', 'error_message', 'http_status', 'provider_latency_ms', 'result_count', 'cached_until', 'provider_request_id', 'raw_response', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'cached']
  - constraint: result_count >= 0
  - constraint: provider_latency_ms is null OR provider_latency_ms >= 0
  - constraint: http_status is null OR (http_status >= 100 AND http_status <= 599)
  - constraint: unique(workspace_id, request_fingerprint, created_at::date)  -- optional daily dedupe window
- `search_results.json` — Normalized result items returned from Brave for either web search or local search. Stored per search_request for reproducibility and auditing. (33 rows; fields: ['id', 'search_request_id', 'workspace_id', 'result_type', 'rank', 'title', 'url', 'snippet', 'display_domain', 'language', 'published_at', 'provider_item_id', 'place', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'redacted', 'deleted']
  - constraint: rank >= 1
  - constraint: unique(search_request_id, rank)
  - constraint: result_type = 'web' implies url is not null
  - constraint: result_type = 'local_place' implies place is not null
- `usage_ledger.json` — Append-only ledger of billable usage for rate limiting and monthly quotas. One row per completed request plus optional per-item increments. (30 rows; fields: ['id', 'workspace_id', 'api_key_id', 'search_request_id', 'event_type', 'tool_name', 'quantity', 'billable', 'period_month', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['request', 'result_item']
  - constraint: quantity >= 0
  - constraint: unique(search_request_id, event_type)  -- at most one ledger row per type per request (aggregation)
  - constraint: period_month matches ^\d{4}-\d{2}$

## Business rules enforced by the tools

- Each brave_web_search invocation MUST create a search_requests row with tool_name='brave_web_search' and a non-empty query_text, and MUST end in status in {'succeeded','failed','cancelled','cached'}.
- Each brave_local_search invocation MUST create a search_requests row with tool_name='brave_local_search'; if no local_place results are returned or the provider local endpoint errors with a retryable/unsupported condition, fallback_to_web MUST be set true and a web search MUST be performed and stored under the same search_requests row (raw_response may include both responses, redacted).
- A workspace with status != 'active' MUST NOT execute outbound provider requests; attempts MUST create a search_requests row with status='failed' and an appropriate error_code.
- An api_keys row with status in {'disabled','revoked'} MUST NOT be used for outbound requests; attempts MUST fail before contacting the provider.
- Before executing a request, the system MUST enforce workspace monthly_request_quota by summing usage_ledger.quantity where event_type='request' and billable=true for the same workspace_id and period_month; if quota exceeded, the request MUST be rejected or recorded as failed without contacting the provider.
- After a request succeeds or is served from cache, the system MUST write exactly one usage_ledger row with event_type='request' (billable true unless explicitly waived) and quantity=1 for the corresponding search_request_id.
- After persisting result items, the system MUST write exactly one usage_ledger row with event_type='result_item' and quantity=search_requests.result_count (billable true unless explicitly waived) for the corresponding search_request_id.
- search_results.rank MUST be contiguous starting at 1 within a search_request_id; duplicates MUST be rejected by unique(search_request_id, rank).
- For search_results where result_type='web', url MUST be non-null; for result_type='local_place', place MUST be non-null and SHOULD include at minimum an address or geo coordinate when available.
- Caching: if a new request matches an existing succeeded request by (workspace_id, request_fingerprint) and cached_until > now(), the system SHOULD set status='cached', copy/attach results, and MUST still record usage_ledger per policy (either billable or not, but consistently).
- Retention: deleting a workspace MUST transition it to status='deleted' and MUST cascade result retention by transitioning related search_results to status='deleted' (hard delete optional) while preserving usage_ledger as append-only for audit.