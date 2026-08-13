# Time MCP Server — local MCP environment

This backend powers a Time utility MCP server that returns formatted current time, relative time calculations, timestamps, timezone conversions, and calendar-derived values (days in month, week/ISO week). It stores API clients/keys for access control, logs each tool invocation for observability/billing, and keeps optional user/workspace preferences such as default timezone and format.

Repository: https://github.com/yokingma/time-mcp
Homepage: https://smithery.ai/server/@yokingma/time-mcp

## Datastore

- `workspaces.json` — Tenant/workspace container for API clients, keys, preferences, and usage limits. (18 rows; fields: ['id', 'name', 'status', 'default_timezone', 'default_time_format', 'rate_limit_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
  - constraint: default_timezone must be a valid IANA timezone when not null
- `api_keys.json` — API keys used by clients to authenticate against the MCP server; scoped to a workspace and used for rate limiting and logging. (18 rows; fields: ['id', 'workspace_id', 'name', 'status', 'key_prefix', 'key_hash', 'scopes', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_prefix)
  - constraint: key_hash length >= 32
- `timezone_registry.json` — Cached registry of valid IANA timezones supported by the server runtime (used to validate timezone parameters and preferences). (18 rows; fields: ['id', 'iana_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['enabled', 'disabled']
  - constraint: unique(iana_name)
- `tool_invocations.json` — Immutable audit/usage log of every MCP tool call (request parameters, derived normalization, response metadata). (20 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'request_params', 'normalized_time', 'normalized_date', 'source_timezone', 'target_timezone', 'output_format', 'response_payload', 'error_code', 'error_message', 'duration_ms', 'request_ip', 'created_at', 'updated_at'])
  - lifecycle `status`: ['accepted', 'succeeded', 'failed', 'rate_limited']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete set null
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: tool_name = 'current_time' implies output_format is not null
- `rate_limit_counters.json` — Rolling per-minute counters used to enforce workspace/key rate limits for tool invocations. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'window_start', 'count', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'sealed', 'expired']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key (api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(workspace_id, api_key_id, window_start)
  - constraint: count >= 0

## Business rules enforced by the tools

- Tool parameters must be persisted in tool_invocations.request_params exactly as received, alongside parsed/normalized fields when parsing succeeds.
- current_time: format must be one of the allowed enums; if client omits timezone, use workspaces.default_timezone if set, else server default (UTC). tool_invocations.output_format must equal the effective format used.
- relative_time: request_params.time must parse as 'YYYY-MM-DD HH:mm:ss' in the effective timezone (workspace default or UTC). On parse failure, invocation status=failed with error_code='INVALID_TIME'.
- days_in_month: if date is provided it must parse as 'YYYY-MM-DD'; if omitted, use current date in effective timezone. normalized_date must be stored as YYYY-MM-DD.
- get_timestamp: if time omitted, use current time in effective timezone; if provided must parse as 'YYYY-MM-DD HH:mm:ss'. normalized_time must be stored in UTC.
- convert_time: sourceTimezone and targetTimezone must both exist in timezone_registry with status='enabled' (or be validated by runtime and then inserted/enabled); time must parse as 'YYYY-MM-DD HH:mm:ss' in sourceTimezone. source_timezone/target_timezone must be recorded.
- get_week_year: if date provided it must parse as 'YYYY-MM-DD'; if omitted, use current date in effective timezone. normalized_date must be recorded.
- Authentication: each request must resolve to an active workspace and an active, non-expired api_key (if api keys are required by deployment); otherwise reject and log an invocation with status=failed and error_code='UNAUTHORIZED'.
- Rate limiting: before executing a tool, increment (or attempt to increment) the rate_limit_counters bucket for (workspace_id, api_key_id, current minute). If count would exceed workspaces.rate_limit_per_minute, do not execute; create tool_invocations row with status=rate_limited.
- API key expiry: api_keys.status must transition to 'expired' automatically when now() >= expires_at; expired keys must not be allowed to invoke tools.
- Data retention: tool_invocations.response_payload may be null or truncated based on retention policy, but tool_name, status, timestamps, and request_params must be retained for auditing.