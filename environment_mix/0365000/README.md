# Mixpanel Integration — local MCP environment

This backend stores Mixpanel workspace connections (projects and credentials), cached Mixpanel entities (saved funnels/cohorts), and an auditable log of analytics queries executed through the integration. The main workflows are: configure a workspace connection, issue analytics/report queries (optionally cached), and list/use saved entities (funnels/cohorts) as inputs to report queries.

Repository: https://github.com/dragonkhoi/mixpanel-mcp
Homepage: https://smithery.ai/server/@dragonkhoi/mixpanel-mcp

## Datastore

- `workspaces.json` — Represents a connected Mixpanel project/workspace within this integration, including authentication, defaults, and lifecycle status. (20 rows; fields: ['id', 'name', 'mixpanel_project_id', 'service_account_label', 'auth_type', 'auth_secret_ref', 'region', 'timezone', 'default_length_unit', 'status', 'last_successful_sync_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(mixpanel_project_id, region)
  - constraint: name <> ''
  - constraint: mixpanel_project_id > 0
- `workspace_api_keys.json` — API keys for clients using this integration; used for authentication, authorization, rate limiting, and attribution of tool calls. (34 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'scopes', 'status', 'rate_limit_per_minute', 'daily_quota', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute between 1 and 6000
  - constraint: daily_quota between 1 and 500000
- `mixpanel_entities.json` — Locally cached Mixpanel saved objects used by tools (funnels and cohorts). Enables list_saved_funnels/list_saved_cohorts and provides stable IDs and metadata for later report queries. (31 rows; fields: ['id', 'workspace_id', 'entity_type', 'mixpanel_entity_id', 'name', 'definition', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: unique(workspace_id, entity_type, mixpanel_entity_id)
  - constraint: name <> ''
- `analytics_queries.json` — Audit log and cache index for every tool invocation that queries Mixpanel (segmentation, funnels, retention, profiles, JQL, top events/properties). Stores normalized query type, parameters, timing, and status. (39 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'query_type', 'parameters', 'mixpanel_request', 'cache_key', 'cache_ttl_seconds', 'status', 'started_at', 'completed_at', 'duration_ms', 'http_status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: http_status is null or (http_status between 100 and 599)
  - constraint: cache_ttl_seconds is null or (cache_ttl_seconds between 1 and 86400)
  - constraint: parameters must be valid JSON object
- `analytics_query_results.json` — Stores response payloads from Mixpanel for completed queries, enabling caching, later inspection, and consistent reads for tools that return lists/aggregates. (39 rows; fields: ['id', 'query_id', 'workspace_id', 'cache_key', 'content_type', 'result_json', 'result_text', 'result_bytes', 'status', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'evicted']
  - constraint: unique(query_id)
  - constraint: result_bytes >= 0
  - constraint: cache_key is null or cache_key <> ''
  - constraint: (content_type = 'application/json' and result_json is not null) or (content_type = 'text/plain' and result_text is not null)

## Business rules enforced by the tools

- Every tool call must create an analytics_queries row with tool_name set to the called tool and parameters stored as the exact JSON object received ({} allowed).
- Tools that produce Mixpanel reads (all except list_saved_funnels/list_saved_cohorts) must transition analytics_queries.status queued->running->(succeeded|failed). On success, analytics_query_results must be created with unique(query_id).
- list_saved_funnels and list_saved_cohorts must read from mixpanel_entities where entity_type matches and status != 'deleted'. If a background sync refreshes entities, it must upsert by unique(workspace_id, entity_type, mixpanel_entity_id) and mark unseen entities as 'stale' rather than deleting immediately.
- query_funnel_report must validate that the referenced funnel_id exists either in mixpanel_entities(entity_type='funnel') for the workspace or is explicitly allowed as an ad-hoc Mixpanel ID; if not, the query must fail with analytics_queries.status='failed' and an error_message.
- query_retention_report must enforce mutual exclusivity of 'interval' and 'unit' within analytics_queries.parameters when present (only one may be provided).
- custom_jql requires the calling API key to include scope 'exec:jql'; otherwise reject and record a failed analytics_queries row with error_code='forbidden_scope'.
- All tools must enforce workspace status='active' before contacting Mixpanel; if workspace is disabled/error, do not call Mixpanel and record analytics_queries.status='failed'.
- Caching: if analytics_queries.cache_key is set, the system may return an existing analytics_query_results row with status='fresh' and expires_at > now() instead of calling Mixpanel; otherwise it must create a new analytics_queries row and fetch.
- Rate limits and quotas: for a given workspace_api_keys.id, the number of analytics_queries created in the last minute must be <= rate_limit_per_minute and per day <= daily_quota; if exceeded, reject and do not create a succeeded query.
- Result retention: analytics_query_results rows older than their expires_at may be marked 'stale'; storage pressure may mark any stale row as 'evicted' by setting status='evicted' and nulling result_json/result_text while retaining metadata for audit.