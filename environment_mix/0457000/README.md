# Coding Prompt Engineer — local MCP environment

This backend stores coding prompt rewrite requests and their generated rewrites, including the model/runtime metadata used to produce them. The main workflow is: accept a rewrite request, execute a rewrite job, persist the output, and track status plus basic observability for API usage.

Repository: https://github.com/hireshBrem/prompt-engineer-mcp-server
Homepage: https://smithery.ai/server/@hireshBrem/prompt-engineer-mcp-server

## Datastore

- `api_keys.json` — API credentials used to authenticate clients calling rewrite_coding_prompt, with basic enable/disable lifecycle and quota settings. (11 rows; fields: ['id', 'key_hash', 'label', 'status', 'requests_per_minute_limit', 'monthly_requests_limit', 'monthly_requests_used', 'month_window_start', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit >= 1
  - constraint: monthly_requests_limit IS NULL OR monthly_requests_limit >= 1
  - constraint: monthly_requests_used >= 0
- `rewrite_requests.json` — A single invocation of rewrite_coding_prompt, capturing the caller context, input prompt (if available), and the resulting status. The tool surface has no parameters, so inputs may be inferred from server context (e.g., last user message) or stored as empty when not provided. (18 rows; fields: ['id', 'api_key_id', 'status', 'source_prompt', 'source_language_hint', 'request_context', 'client_request_id', 'error_code', 'error_message', 'queued_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(api_key_id, client_request_id) WHERE client_request_id IS NOT NULL
  - constraint: error_code IS NULL OR status = 'failed'
  - constraint: finished_at IS NULL OR finished_at >= started_at
  - constraint: started_at IS NULL OR started_at >= queued_at
- `rewrite_outputs.json` — The generated rewritten prompt(s) and structured guidance produced for a rewrite request. One request may produce multiple variants. (18 rows; fields: ['id', 'rewrite_request_id', 'variant_index', 'status', 'rewritten_prompt', 'structured_sections', 'quality_score', 'created_at', 'updated_at'])
  - lifecycle `status`: ['generated', 'redacted', 'deleted']
  - constraint: unique(rewrite_request_id, variant_index)
  - constraint: variant_index >= 0
  - constraint: quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)
- `model_runs.json` — Execution metadata for the LLM/tooling run that produced outputs for a rewrite request (provider, model, token accounting, latency). (19 rows; fields: ['id', 'rewrite_request_id', 'status', 'provider', 'model', 'prompt_template_version', 'input_tokens', 'output_tokens', 'total_tokens', 'latency_ms', 'cost_usd', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['started', 'succeeded', 'failed']
  - constraint: input_tokens IS NULL OR input_tokens >= 0
  - constraint: output_tokens IS NULL OR output_tokens >= 0
  - constraint: total_tokens IS NULL OR total_tokens >= 0
  - constraint: latency_ms IS NULL OR latency_ms >= 0
- `audit_events.json` — Append-only audit log for requests, rate limiting, quota checks, and administrative actions on API keys. (19 rows; fields: ['id', 'event_type', 'api_key_id', 'rewrite_request_id', 'ip_address', 'user_agent', 'details', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['REQUEST_RECEIVED', 'REQUEST_QUEUED', 'REQUEST_STARTED', 'REQUEST_SUCCEEDED', 'REQUEST_FAILED', 'REQUEST_CANCELLED', 'RATE_LIMIT_BLOCK', 'QUOTA_BLOCK', 'API_KEY_CREATED', 'API_KEY_DISABLED', 'API_KEY_REVOKED']
  - constraint: created_at IS NOT NULL
  - constraint: NOT (rewrite_request_id IS NULL AND api_key_id IS NULL) OR event_type IN ('API_KEY_CREATED','API_KEY_DISABLED','API_KEY_REVOKED')

## Business rules enforced by the tools

- Calling rewrite_coding_prompt MUST create a rewrite_requests row with status='queued' (or directly 'running' for synchronous execution) even though the tool has no explicit parameters; any inferred prompt text may be stored in rewrite_requests.source_prompt.
- A rewrite_requests row MAY have api_key_id NULL for unauthenticated/internal calls; if api_key_id is present, api_keys.status MUST be 'active' at request start.
- If api_keys.monthly_requests_limit is not null, the service MUST reject new requests when monthly_requests_used >= monthly_requests_limit, set rewrite_requests.status='failed', rewrite_requests.error_code='QUOTA_EXCEEDED', and append an audit_events row with event_type='QUOTA_BLOCK'.
- The service MUST enforce requests_per_minute_limit per api_key_id (or per IP when api_key_id is null); when exceeded it MUST not start a model_runs row and MUST emit audit_events.event_type='RATE_LIMIT_BLOCK'.
- A rewrite_requests row with status='succeeded' MUST have at least one rewrite_outputs row with status='generated'.
- rewrite_outputs.rewrite_request_id MUST reference an existing rewrite_requests.id; deleting a rewrite request in practice should be implemented as status terminalization (cancelled/failed) and/or output redaction, not hard deletes.
- For each rewrite_request_id, rewrite_outputs.variant_index MUST be unique and start at 0 for the first created variant (gaps allowed only if a variant is deleted).
- Each model_runs row MUST belong to exactly one rewrite request; if model_runs.status='failed' then rewrite_requests.status MUST be 'failed' unless the system retries and creates a new model_runs that succeeds, in which case the request may end 'succeeded' and the failed run remains for diagnostics.
- Status transitions MUST follow the declared lifecycle transitions; direct transitions from 'queued' to 'succeeded' without 'running' are invalid unless the implementation explicitly uses synchronous processing and sets queued_at and started_at to the same instant.