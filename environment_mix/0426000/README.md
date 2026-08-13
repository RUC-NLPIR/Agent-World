# SerpApi Search Server — local MCP environment

This backend powers a SerpApi-compatible search server that accepts search requests, executes them against upstream search providers, and returns normalized results. It stores API clients/keys, each search request (query) with lifecycle and parameters, the corresponding result sets, and metered usage for quota and billing enforcement.

Repository: https://github.com/zm1990s/panw
Homepage: https://smithery.ai/server/@zm1990s/serpapi

## Datastore

- `api_clients.json` — Represents an owning entity (user/team/service) that can authenticate and consume the SerpApi Search Server. Holds quota plan and status for access control. (12 rows; fields: ['id', 'name', 'status', 'default_engine', 'daily_request_quota', 'monthly_request_quota', 'max_requests_per_minute', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: daily_request_quota >= 0
  - constraint: monthly_request_quota >= 0
  - constraint: max_requests_per_minute >= 0
- `api_keys.json` — API keys used to authenticate calls to the search endpoint. Keys are stored as hashes; only the prefix is stored for lookup/diagnostics. (12 rows; fields: ['id', 'client_id', 'status', 'key_prefix', 'key_hash', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_prefix)
  - constraint: unique(key_hash)
  - constraint: fk(api_keys.client_id) references api_clients.id on delete restrict
- `search_requests.json` — Every invocation of the `search` tool. Stores request payload (even if empty), inferred defaults, execution metadata, and lifecycle state. (19 rows; fields: ['id', 'client_id', 'api_key_id', 'status', 'tool_name', 'raw_parameters', 'engine', 'request_ip', 'user_agent', 'idempotency_key', 'http_status', 'error_code', 'error_message', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'rate_limited']
  - constraint: fk(search_requests.client_id) references api_clients.id on delete restrict
  - constraint: fk(search_requests.api_key_id) references api_keys.id on delete set null
  - constraint: duration_ms >= 0
  - constraint: http_status >= 100 and http_status <= 599
- `search_results.json` — Stores the response payload produced for a search request, including normalized fields and raw upstream JSON for fidelity. (19 rows; fields: ['id', 'search_request_id', 'status', 'upstream_provider', 'raw_response', 'normalized_response', 'result_count', 'cache_hit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'redacted']
  - constraint: fk(search_results.search_request_id) references search_requests.id on delete cascade
  - constraint: unique(search_request_id)
  - constraint: result_count >= 0
- `usage_events.json` — Append-only metering events for quota/rate enforcement and analytics. One or more events may be emitted per request (e.g., attempted, succeeded). (18 rows; fields: ['id', 'client_id', 'api_key_id', 'search_request_id', 'event_type', 'units', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['request_received', 'request_succeeded', 'request_failed', 'rate_limited']
  - constraint: fk(usage_events.client_id) references api_clients.id on delete restrict
  - constraint: fk(usage_events.api_key_id) references api_keys.id on delete set null
  - constraint: fk(usage_events.search_request_id) references search_requests.id on delete cascade
  - constraint: units >= 0

## Business rules enforced by the tools

- Each `search` tool call creates exactly one search_requests row with tool_name='search' and raw_parameters equal to the incoming JSON object (empty object allowed).
- A search_requests row MUST transition status: received -> running -> (succeeded|failed) OR received -> rate_limited/failed. No other transitions are permitted.
- If the authenticated api_client.status != 'active' or api_key.status != 'active' (when present), the request is rejected and a search_requests row is stored with status='failed' and http_status in 401..403.
- Rate limiting: if requests in the last 60 seconds for a client exceed api_clients.max_requests_per_minute, the request is not executed and search_requests.status='rate_limited' with http_status=429; a usage_events row with event_type='rate_limited' and units=0 is emitted.
- Quota limiting: if successful requests today exceed daily_request_quota OR successful requests this month exceed monthly_request_quota, the request is not executed and is marked rate_limited with http_status=429; usage_events.rate_limited is emitted.
- On successful execution, exactly one search_results row is created for the search_request (unique(search_request_id)), and search_requests.status is set to 'succeeded' with finished_at and duration_ms populated.
- On failed execution (including upstream/provider errors), no search_results row is required, search_requests.status='failed', and error_code/error_message must be set.
- Usage metering: a usage_events row with event_type='request_received' is emitted for every request; additionally, exactly one of request_succeeded/request_failed/rate_limited must be emitted per request, and only request_succeeded may have units=1 (policy default).
- Idempotency: if idempotency_key is provided and a previous search_requests row exists for the same client_id and idempotency_key, the server must return the previously stored search_results (if succeeded) or the prior terminal failure/rate-limit response without creating a new request.