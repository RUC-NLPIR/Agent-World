# Google Maps — local MCP environment

This backend stores workspaces and API credentials for calling Google Maps/Places, plus a normalized log of each Maps operation (geocode, places search, place details, directions, distance matrix, elevation, reverse geocode) with inputs, outputs, status, and cost/quota accounting. Primary workflows are: authenticate a workspace via an API key, execute a Maps request, persist the request/response for auditing and caching, and accumulate usage for quota enforcement and billing.

Repository: https://github.com/smithery-ai/mcp-servers
Homepage: https://smithery.ai/server/@smithery-ai/google-maps

## Datastore

- `workspaces.json` — Tenant container for Google Maps usage, configuration, and quota. All requests and keys belong to a workspace. (12 rows; fields: ['id', 'name', 'status', 'default_region', 'default_language', 'quota_daily_requests', 'quota_monthly_requests', 'quota_daily_cost_usd', 'quota_monthly_cost_usd', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: quota_daily_requests >= 0
  - constraint: quota_monthly_requests >= 0
  - constraint: quota_daily_cost_usd >= 0
- `api_keys.json` — API keys used by clients of this service to authenticate and authorize requests per workspace (not the Google API key). (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'prefix', 'status', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(prefix)
  - constraint: length(prefix) >= 6
- `provider_connections.json` — Per-workspace configuration for calling Google Maps Platform (e.g., Google API key, project metadata, and enablement flags). (12 rows; fields: ['id', 'workspace_id', 'provider', 'status', 'google_api_key_ciphertext', 'google_project_id', 'allowed_endpoints', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, provider)
  - constraint: json_array_length(allowed_endpoints) >= 1
  - constraint: allowed_endpoints elements in ['maps_geocode','maps_reverse_geocode','maps_search_places','maps_place_details','maps_distance_matrix','maps_elevation','maps_directions']
- `maps_requests.json` — Canonical request log for all Google Maps tools. Stores sanitized inputs, provider request metadata, response payload, errors, latency, and cost for quota and auditing. (21 rows; fields: ['id', 'workspace_id', 'api_key_id', 'provider_connection_id', 'tool_name', 'status', 'input', 'normalized_input', 'cache_key', 'provider_http_method', 'provider_url', 'provider_status_code', 'provider_request_id', 'response', 'error_code', 'error_message', 'latency_ms', 'billable_units', 'estimated_cost_usd', 'deduped_from_request_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: foreign key(provider_connection_id) references provider_connections(id) on delete restrict
  - constraint: foreign key(deduped_from_request_id) references maps_requests(id) on delete set null
- `usage_rollups.json` — Aggregated usage for quota enforcement and reporting per workspace, time window, and tool. (17 rows; fields: ['id', 'workspace_id', 'period_start', 'period_end', 'period_type', 'tool_name', 'request_count', 'billable_units', 'estimated_cost_usd', 'created_at', 'updated_at'])
  - lifecycle `period_type`: ['day', 'month']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, period_type, period_start, tool_name)
  - constraint: period_end > period_start
  - constraint: request_count >= 0

## Business rules enforced by the tools

- Every tool invocation (maps_geocode, maps_reverse_geocode, maps_search_places, maps_place_details, maps_distance_matrix, maps_elevation, maps_directions) MUST create a maps_requests row with tool_name set accordingly and input containing the raw tool payload (even if empty).
- A request MUST be associated to exactly one workspace via api_key_id, and api_keys.workspace_id MUST equal maps_requests.workspace_id.
- provider_connections.status MUST be 'active' to execute a request; otherwise the request MUST end in status='failed' with error_code='provider_connection_disabled' or 'provider_connection_error'.
- workspaces.status MUST be 'active' to execute a request; if 'suspended' or 'deleted', the request MUST be rejected/recorded as status='failed' with error_code='workspace_inactive'.
- api_keys.status MUST be 'active' and (expires_at is null or expires_at > now) to execute a request; otherwise record status='failed' with error_code='api_key_revoked_or_expired'.
- Quota enforcement: before executing provider call, the service MUST compute projected daily and monthly totals (request_count and estimated_cost_usd) and MUST reject if any would exceed workspaces.quota_*; the rejected attempt MUST still be recorded in maps_requests with status='failed' and error_code='quota_exceeded'.
- Caching: if cache_key is present and an unexpired previous maps_requests row with the same cache_key and status='succeeded' exists, the service MAY skip the provider call and create a new maps_requests row with deduped_from_request_id referencing the cached request and status='succeeded'.
- Status transitions for maps_requests MUST follow the declared lifecycle; once in succeeded/failed/cancelled, the row MUST be immutable except for adding late-arriving provider metadata fields (provider_request_id, provider_status_code) and updated_at.
- estimated_cost_usd MUST be derived from tool_name and request characteristics stored in normalized_input (e.g., matrix elements count, waypoints count) and MUST be non-negative; billable_units MUST be non-negative and consistent with the same characteristics.
- usage_rollups MUST be updated transactionally when a maps_requests row reaches a terminal state (succeeded/failed/cancelled), incrementing both the tool-specific bucket and the '*' bucket for the same workspace and period.