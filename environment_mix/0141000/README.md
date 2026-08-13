# RT-Prompt — local MCP environment

RT-Prompt stores prompt templates and a lightweight suggestion-generation request log. The main workflow is: users call one of the suggestion tools (backend/frontend/general/ui/crud) which selects a matching prompt template (by category + filters), renders it with the user context, and returns it; the Feishu tool fetches a named prompt template. The backend tracks versions, publication status, and request auditing/quotas per API key.

Repository: https://github.com/yuyao1999/rt-prompt-mcp
Homepage: https://smithery.ai/server/@yuyao1999/rt-prompt-mcp-server

## Datastore

- `workspaces.json` — Tenant container for API keys, prompt libraries, and request logs. Enables per-team customization and quota enforcement. (12 rows; fields: ['id', 'name', 'slug', 'status', 'default_locale', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name <> ''
  - constraint: default_locale <> ''
- `api_keys.json` — API credentials used to authenticate calls to the tools and to enforce per-workspace quotas. Keys belong to a workspace. (27 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'rate_limit_per_min', 'daily_request_quota', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_prefix)
  - constraint: rate_limit_per_min >= 1 and rate_limit_per_min <= 6000
  - constraint: daily_request_quota >= 0 and daily_request_quota <= 1000000
- `prompt_templates.json` — Versioned prompt templates that power suggestion tools and Feishu prompt retrieval. A template can be selected by category/type filters or by exact prompt_name for Feishu. (34 rows; fields: ['id', 'workspace_id', 'prompt_name', 'category', 'filters', 'template_text', 'output_format', 'version', 'is_default', 'status', 'created_at', 'updated_at', 'published_at'])
  - lifecycle `status`: ['draft', 'published', 'archived']
  - constraint: unique(workspace_id, prompt_name, version)
  - constraint: unique(workspace_id, category, is_default) where is_default = true
  - constraint: prompt_name <> ''
  - constraint: template_text <> ''
- `suggestion_requests.json` — Audit log for all tool invocations, capturing parameters, matched template, rendering outcome, latency, and quota accounting. (38 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'parameters', 'context', 'database_type', 'language', 'framework', 'device_type', 'task_type', 'design_type', 'platform', 'base_path', 'prompt_name', 'matched_template_id', 'rendered_prompt', 'error_code', 'error_message', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'fulfilled', 'rejected', 'error']
  - constraint: latency_ms is null or (latency_ms >= 0 and latency_ms <= 300000)
  - constraint: parameters is a JSON object
  - constraint: tool_name in allowed enum
  - constraint: If tool_name = 'get_feishu_prompt' then prompt_name is not null and prompt_name <> ''
- `quota_counters.json` — Materialized counters for fast quota/rate checks per API key and time window. Updated transactionally with suggestion_requests creation. (30 rows; fields: ['id', 'api_key_id', 'window_type', 'window_start', 'request_count', 'rejected_count', 'created_at', 'updated_at'])
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: request_count >= 0
  - constraint: rejected_count >= 0
  - constraint: rejected_count <= request_count

## Business rules enforced by the tools

- Every tool call must authenticate with an active api_keys row; api_keys.status must be 'active' and the owning workspaces.status must be 'active', otherwise the request is recorded as suggestion_requests.status='rejected' with error_code='AUTH_DISABLED'.
- get_backend_suggestions must select a published prompt_templates row where category='backend' and filters match databaseType/language when provided; if no match, it must fall back to the unique published template with category='backend' and is_default=true (if present).
- get_frontend_suggestions must select a published prompt_templates row where category='frontend' and filters match framework/deviceType when provided; otherwise fall back to category='frontend' and is_default=true.
- get_general_suggestions must select a published prompt_templates row where category='general' and filters match taskType when provided; otherwise fall back to category='general' and is_default=true.
- get_ui_design_suggestions must select a published prompt_templates row where category='ui_design' and filters match designType/platform when provided; otherwise fall back to category='ui_design' and is_default=true.
- get_rt_crud_suggestions must select a published prompt_templates row where category='rt_crud'; if base_path is provided, it must be dot-separated and match regex ^[a-zA-Z_]\w*(\.[a-zA-Z_]\w*)*$ or the request is rejected with error_code='INVALID_BASE_PATH'.
- get_feishu_prompt must locate a published prompt_templates row in the caller's workspace where prompt_name equals the provided prompt_name; if none exists, the request is rejected with error_code='PROMPT_NOT_FOUND'.
- When rendering, placeholders {{context}}, {{databaseType}}, {{language}}, {{framework}}, {{deviceType}}, {{taskType}}, {{designType}}, {{platform}}, {{base_path}}, {{prompt_name}} must be substituted from suggestion_requests.parameters when present; missing optional values must render as empty string or be conditionally omitted per template logic.
- For each successful or failed call, a suggestion_requests row must be created with parameters stored verbatim and denormalized columns populated when present for indexing.
- Rate limit enforcement: for each call, increment (or create) quota_counters for window_type='minute' at the current minute; if request_count would exceed api_keys.rate_limit_per_min, the call must be rejected (status='rejected', error_code='RATE_LIMIT') and rejected_count incremented.
- Daily quota enforcement: for each call, increment (or create) quota_counters for window_type='day' at current day; if request_count would exceed api_keys.daily_request_quota (when > 0), the call must be rejected with error_code='DAILY_QUOTA_EXCEEDED'.
- prompt_templates status transitions must follow: draft -> published -> archived; publishing sets published_at, archiving does not clear history; only one template per (workspace_id, category) may have is_default=true.
- Foreign key integrity: deleting a workspace is a soft delete (status='deleted'); api_keys and prompt_templates remain but cannot be used when workspace is not active; suggestion_requests are immutable after creation except for status/latency/error fields updated during processing.