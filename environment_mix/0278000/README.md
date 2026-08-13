# Wolfram Alpha LLM API — local MCP environment

This backend stores Wolfram Alpha LLM API query sessions, including the user’s prompt, the resolved/normalized query sent to Wolfram, and the returned results. It also stores interpretation/assumption candidates for ambiguous queries and links follow-up queries that apply a chosen assumption set back to the original query.

Repository: https://github.com/henryhawke/wolfram-llm-mcp
Homepage: https://smithery.ai/server/@henryhawke/wolfram-llm-mcp

## Datastore

- `api_keys.json` — Issued client credentials used to authenticate callers and apply per-key quotas/rate limits for Wolfram query execution. (17 rows; fields: ['id', 'key_hash', 'label', 'status', 'quota_daily_requests', 'rate_limit_per_minute', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: quota_daily_requests >= 0
  - constraint: rate_limit_per_minute >= 0
- `query_sessions.json` — Top-level query interaction, including the original user prompt and any follow-up attempt that applies assumptions. Serves both wolfram_query and wolfram_query_with_assumptions as the shared parent record. (17 rows; fields: ['id', 'api_key_id', 'parent_query_id', 'tool_name', 'user_query_text', 'normalized_query_text', 'client_metadata', 'status', 'ambiguity_detected', 'latency_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'needs_assumptions', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(parent_query_id) references query_sessions(id) on delete set null
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: tool_name in ('wolfram_query','wolfram_query_with_assumptions')
- `query_assumptions.json` — Stores assumption/interpretation candidates returned for an ambiguous query and the selected set used for a follow-up disambiguated request. (18 rows; fields: ['id', 'query_id', 'assumption_key', 'assumption_label', 'candidates', 'selected_candidate', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['unselected', 'selected', 'applied']
  - constraint: fk(query_id) references query_sessions(id) on delete cascade
  - constraint: unique(query_id, assumption_key)
  - constraint: candidates must be a non-empty array when query_sessions.status = 'needs_assumptions'
  - constraint: if status in ('selected','applied') then selected_candidate is not null
- `wolfram_responses.json` — Stores upstream Wolfram Alpha LLM API responses, both the raw payload and extracted display-friendly fields for fast reads and auditing. (19 rows; fields: ['id', 'query_id', 'upstream_request', 'upstream_response', 'result_text', 'pods', 'assumptions', 'upstream_status', 'http_status_code', 'created_at', 'updated_at'])
  - lifecycle `upstream_status`: ['success', 'error', 'timeout']
  - constraint: fk(query_id) references query_sessions(id) on delete cascade
  - constraint: unique(query_id)
  - constraint: http_status_code is null or (http_status_code >= 100 and http_status_code <= 599)
- `usage_events.json` — Immutable usage ledger for quota enforcement, auditing, and cost tracking per API key and query. (17 rows; fields: ['id', 'api_key_id', 'query_id', 'event_type', 'billable', 'cost_units', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['request_accepted', 'request_succeeded', 'request_failed', 'request_rate_limited', 'request_quota_exceeded']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(query_id) references query_sessions(id) on delete set null
  - constraint: cost_units >= 0
  - constraint: if event_type in ('request_succeeded') then billable = true

## Business rules enforced by the tools

- Both tools accept an empty-JSON schema at the MCP boundary; the service must obtain the actual user query text from the surrounding MCP message context and persist it as query_sessions.user_query_text.
- Creating a wolfram_query call inserts query_sessions(tool_name='wolfram_query', status='queued') and a usage_events row with event_type='request_accepted'.
- If upstream indicates ambiguity (multiple interpretations/assumptions), the service must set query_sessions.status='needs_assumptions', query_sessions.ambiguity_detected=true, insert/update query_assumptions rows for each assumption group, and persist the full upstream payload in wolfram_responses.
- A wolfram_query_with_assumptions call must create a new query_sessions row with parent_query_id pointing to the original ambiguous query; it must not mutate the parent query’s user_query_text.
- For wolfram_query_with_assumptions, the service must mark chosen query_assumptions.status='applied' and must include the selected_candidate(s) in wolfram_responses.upstream_request for the follow-up query.
- A query_session can have at most one wolfram_responses row (unique(query_id)); retries must either overwrite that row with updated_at changed or create a new query_session (implementation choice), but uniqueness must be preserved.
- api_keys.status must be 'active' to accept requests; otherwise record usage_events(event_type='request_failed' or 'request_rate_limited' as appropriate) and do not create a query_sessions row.
- Daily quota enforcement: for a given api_key_id and UTC day, the count/sum of billable usage_events.cost_units for event_type='request_succeeded' must be <= api_keys.quota_daily_requests; if exceeded, record usage_events(event_type='request_quota_exceeded', billable=false) and reject the query.
- Rate limit enforcement: for a given api_key_id and sliding 60-second window, accepted requests must be <= api_keys.rate_limit_per_minute; on exceed, record usage_events(event_type='request_rate_limited', billable=false) and reject without calling upstream.
- Status transitions must follow the declared lifecycle graphs; e.g., query_sessions.status cannot move from 'succeeded' back to 'running'.
- Deleting an api_key is not allowed while referenced; instead set status='revoked'.
- query_assumptions rows are only allowed for query_sessions where ambiguity_detected=true; otherwise insertion must fail validation.