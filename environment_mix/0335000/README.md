# Giphy API Integration — local MCP environment

This backend powers an integration layer over the Giphy API, storing tenant/workspace configuration (API keys), executing GIF fetch operations (search/random/trending), and persisting responses for auditing, caching, and analytics. Primary workflows are: configure access credentials, issue a request (search/random/trending), store the request/response, and optionally serve cached results while tracking usage.

Repository: https://github.com/magarcia/mcp-server-giphy
Homepage: https://smithery.ai/server/@magarcia/mcp-server-giphy

## Datastore

- `workspaces.json` — Tenant/container for configuration, credentials, and usage tracking for the Giphy integration. (12 rows; fields: ['id', 'name', 'status', 'default_language', 'default_region', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: status in ('active','suspended','deleted')
- `api_credentials.json` — Stores Giphy API credentials and configuration per workspace, including rotation and enable/disable state. (12 rows; fields: ['id', 'workspace_id', 'provider', 'api_key_ciphertext', 'key_fingerprint', 'status', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(workspace_id, provider, key_fingerprint)
  - constraint: provider = 'giphy'
  - constraint: status in ('active','disabled','revoked')
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
- `gif_requests.json` — Captures each tool invocation (search_gifs, get_random_gif, get_trending_gifs) including inputs, execution status, and upstream metadata. Since the tool surface exposes no parameters, inputs are stored as an empty object while still supporting future extension (e.g., search query, tag, limit/offset). (17 rows; fields: ['id', 'workspace_id', 'credential_id', 'tool_name', 'input', 'cache_key', 'status', 'http_status', 'error_code', 'error_message', 'duration_ms', 'created_at', 'updated_at', 'completed_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(credential_id) references api_credentials(id) on delete set null
  - constraint: tool_name in ('search_gifs','get_random_gif','get_trending_gifs')
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
- `gif_responses.json` — Stores the upstream response payload for a request, plus normalized extracted GIF items for faster consumption and caching decisions. (22 rows; fields: ['id', 'request_id', 'workspace_id', 'from_cache', 'expires_at', 'raw_json', 'gif_items', 'result_count', 'created_at', 'updated_at'])
  - constraint: unique(request_id)
  - constraint: fk(request_id) references gif_requests(id) on delete cascade
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: result_count >= 0
- `usage_counters.json` — Aggregated usage counters for rate limiting and cost control per workspace and tool over time windows. (12 rows; fields: ['id', 'workspace_id', 'tool_name', 'window_start', 'window_seconds', 'request_count', 'success_count', 'error_count', 'created_at', 'updated_at'])
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, tool_name, window_start, window_seconds)
  - constraint: window_seconds in (60, 300, 3600, 86400)
  - constraint: request_count >= 0

## Business rules enforced by the tools

- Every tool call (search_gifs, get_random_gif, get_trending_gifs) must create exactly one gif_requests row with tool_name matching the invoked tool and input as a JSON object (empty for the current tool surface).
- A gif_requests row may only reference an api_credentials row whose workspace_id matches the request workspace_id and whose status is 'active'.
- A gif_requests row must follow valid status transitions: queued -> running -> (succeeded|failed|cancelled) or queued -> cancelled.
- On success, a gif_responses row must be created with unique(request_id) and request status must be 'succeeded'. On failure, no gif_responses row may exist and request status must be 'failed'.
- Caching: if cache_key is present and a non-expired gif_responses exists for the same workspace_id and cache_key via a prior request, the system may serve from cache and must set gif_responses.from_cache = true for the served request.
- Rate limiting/quota: before executing an upstream call, increment or reserve usage_counters for (workspace_id, tool_name) in the active window; if the increment would exceed configured limits for the workspace, the request must fail with error_code='quota_exceeded' and must not call upstream.
- Deletion/retention: workspaces in status 'deleted' must reject new gif_requests inserts; existing gif_requests/gif_responses may be retained per policy but must remain FK-consistent.
- http_status must be recorded for any request that reached upstream; duration_ms must be recorded for any request that left 'running' into a terminal state.