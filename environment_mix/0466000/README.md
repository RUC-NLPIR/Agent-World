# Healthcare Data and Medical Information Server — local MCP environment

This backend supports a healthcare information aggregation API that proxies/searches external sources (FDA drug labels, PubMed, clinical trials, ICD-10 lookup, and health topics) and records request/response metadata for observability and usage reporting. Core workflows are: accept a tool call tied to a session, execute an external query, cache/store results for repeatability, and increment per-session and global usage counters for the usage statistics tools.

Repository: https://github.com/Cicatriiz/healthcare-mcp-public
Homepage: https://smithery.ai/server/@Cicatriiz/healthcare-mcp-public

## Datastore

- `sessions.json` — Anonymous or client-associated sessions used to group tool calls and compute usage stats for 'current session' vs 'all sessions'. (12 rows; fields: ['id', 'session_token_hash', 'client_id', 'ip_address', 'user_agent', 'status', 'last_seen_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: unique(session_token_hash)
  - constraint: expires_at is null OR expires_at >= created_at
- `tool_requests.json` — An append-only log of each tool invocation (inputs, timing, outcome) to support caching, troubleshooting, and usage aggregation. (18 rows; fields: ['id', 'session_id', 'tool_name', 'input_params', 'normalized_cache_key', 'status', 'http_status', 'error_code', 'error_message', 'duration_ms', 'result_count', 'cache_hit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: foreign key(session_id) references sessions(id) on delete cascade
  - constraint: duration_ms is null OR duration_ms >= 0
  - constraint: result_count is null OR result_count >= 0
  - constraint: http_status is null OR (http_status >= 100 AND http_status <= 599)
- `cached_responses.json` — Materialized/cached outputs for read-heavy external lookups (FDA, PubMed, clinical trials, ICD-10, health topics). Enables fast repeats and reduces upstream calls. (18 rows; fields: ['id', 'tool_name', 'cache_key', 'request_fingerprint', 'response_payload', 'status', 'source', 'etag', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'invalid']
  - constraint: unique(tool_name, cache_key)
  - constraint: expires_at is null OR expires_at >= created_at
  - constraint: index(tool_name, expires_at)
  - constraint: index(cache_key)
- `usage_rollups.json` — Pre-aggregated usage counters for fast get_usage_stats (per session) and get_all_usage_stats (global). Updated on each tool request completion. (17 rows; fields: ['id', 'scope', 'session_id', 'tool_name', 'window', 'window_start', 'request_count', 'success_count', 'error_count', 'cache_hit_count', 'upstream_call_count', 'total_duration_ms', 'created_at', 'updated_at'])
  - lifecycle `scope`: ['global', 'session']
  - constraint: foreign key(session_id) references sessions(id) on delete cascade
  - constraint: request_count >= 0
  - constraint: success_count >= 0
  - constraint: error_count >= 0

## Business rules enforced by the tools

- Each tool invocation must create a tool_requests row with status='received' then transition to 'running' and finally to exactly one terminal state: 'succeeded' or 'failed'.
- For cacheable tools (fda_drug_lookup, pubmed_search, health_topics, clinical_trials_search, lookup_icd_code), the service must compute normalized_cache_key from normalized inputs; if a cached_responses row exists with status='fresh' and (expires_at is null OR expires_at > now), the request must be served from it and tool_requests.cache_hit=true.
- A cached_responses row must be unique by (tool_name, cache_key); refresh must update response_payload, set status='fresh', and set updated_at to now.
- Sessions must be resolved from an incoming session token; the raw token must never be stored, only sessions.session_token_hash.
- get_usage_stats must return usage aggregated only for the resolved current session_id; get_all_usage_stats must aggregate across all sessions.
- On completion of any tool request (succeeded or failed), usage_rollups must be incremented for: (scope='session', session_id=...), (scope='global'), and optionally per-tool rows (tool_name=<tool>), keeping invariants: success_count+error_count<=request_count and cache_hit_count<=request_count.
- Requests with status='failed' must have error_code and error_message set (non-null) and may have http_status; requests with status='succeeded' must have error_code and error_message null.
- duration_ms must be recorded for running->terminal transitions and must be >= 0; negative durations are rejected.
- If a session is expired or revoked, new tool_requests for that session are rejected and a new session must be created.