# Whimsical Diagram Creator — local MCP environment

This backend stores requests to generate Whimsical diagrams from Mermaid markup, and the resulting Whimsical diagram artifacts (including external IDs/URLs). The primary workflow is: accept a create request, validate/store the Mermaid and title, attempt creation against Whimsical, then persist the resulting diagram metadata and final request status for audit and troubleshooting.

Repository: https://github.com/BrockReece/whimsical-mcp-server
Homepage: https://smithery.ai/server/@BrockReece/whimsical-mcp-server

## Datastore

- `api_keys.json` — API keys used to authenticate clients invoking the diagram creation tool, including status and quotas. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'requests_per_minute_limit', 'diagrams_per_day_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: requests_per_minute_limit between 1 and 6000
  - constraint: diagrams_per_day_limit between 0 and 100000
- `diagram_create_requests.json` — Immutable-ish record of each create_whimsical_diagram invocation, including inputs, validation, and execution outcome. (19 rows; fields: ['id', 'api_key_id', 'title', 'mermaid_markup', 'mermaid_sha256', 'status', 'idempotency_key', 'client_request_id', 'error_code', 'error_message', 'whimsical_http_status', 'attempt_count', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: title length between 1 and 200
  - constraint: mermaid_markup length between 1 and 200000
  - constraint: attempt_count >= 0
- `whimsical_diagrams.json` — Whimsical diagram artifacts created by the service, including external Whimsical identifiers and access URLs. (18 rows; fields: ['id', 'create_request_id', 'api_key_id', 'title', 'mermaid_sha256', 'whimsical_diagram_id', 'whimsical_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(create_request_id) references diagram_create_requests(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: unique(create_request_id)
  - constraint: unique(whimsical_diagram_id) where whimsical_diagram_id is not null
- `usage_counters_daily.json` — Daily usage counters per API key to enforce diagrams_per_day_limit and support billing/monitoring. (12 rows; fields: ['id', 'api_key_id', 'usage_date', 'create_requests_total', 'diagrams_succeeded', 'diagrams_failed', 'created_at', 'updated_at'])
  - constraint: fk(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, usage_date)
  - constraint: create_requests_total >= 0
  - constraint: diagrams_succeeded >= 0

## Business rules enforced by the tools

- create_whimsical_diagram must insert a diagram_create_requests row with title and mermaid_markup exactly as provided, and compute/store mermaid_sha256.
- A diagram_create_requests row must start in status='queued' (or directly 'running' in synchronous mode), then transition following the declared lifecycle only; terminal states are succeeded/failed/cancelled.
- If diagram creation succeeds, the service must create exactly one whimsical_diagrams row referencing the request (unique(create_request_id)) and set diagram_create_requests.status='succeeded' with finished_at set.
- If diagram creation fails, the service must set diagram_create_requests.status='failed', populate error_code and error_message, and set finished_at; it must not create a whimsical_diagrams row.
- Requests must be rejected when api_keys.status != 'active'.
- Per API key, enforce requests_per_minute_limit (rate limiting) and diagrams_per_day_limit (quota). On violation, set request to failed with error_code='RATE_LIMITED' or 'QUOTA_EXCEEDED' (or reject before enqueue), and do not create a diagram artifact.
- Idempotency: if idempotency_key is provided and a prior request exists with the same (api_key_id, idempotency_key), the service must return the prior result and must not create a new request or diagram.
- Validate inputs: title must be 1..200 characters; mermaid_markup must be non-empty and <= 200000 characters; otherwise fail with error_code='VALIDATION_ERROR'.
- usage_counters_daily must be updated transactionally with request creation and final outcome so quota decisions are based on consistent counts.