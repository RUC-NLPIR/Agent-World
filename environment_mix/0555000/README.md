# DataForSEO MCP Server — local MCP environment

This backend persists DataForSEO-powered tasks initiated via the MCP tools, including SERP organic lookups, keyword search volume jobs, and on-page parsing/instant page audits. It stores normalized request parameters, asynchronous execution state, vendor responses, and per-workspace access/quota controls so each tool call can be audited, replayed, and rate-limited.

Repository: https://github.com/moaiandin/mcp-dataforseo
Homepage: https://smithery.ai/server/@moaiandin/mcp-dataforseo

## Datastore

- `workspaces.json` — Tenant container for API usage, billing/quota enforcement, and ownership of all DataForSEO task runs initiated via MCP tools. (12 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_request_limit', 'monthly_cost_usd_limit', 'requests_used_month', 'cost_usd_used_month', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: monthly_request_limit >= 0
  - constraint: monthly_cost_usd_limit >= 0
  - constraint: requests_used_month >= 0
- `api_keys.json` — Keys used by clients to call the MCP server; mapped to a workspace for authorization and quota tracking. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
- `tool_calls.json` — Audit log and execution state for each invocation of an MCP tool; stores raw inputs and normalized routing to a concrete DataForSEO task type. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'request_payload', 'vendor_endpoint', 'vendor_http_status', 'error_code', 'error_message', 'estimated_cost_usd', 'actual_cost_usd', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: estimated_cost_usd >= 0
  - constraint: actual_cost_usd is null or actual_cost_usd >= 0
- `serp_tasks.json` — Normalized storage for SERP Organic tasks and supporting location list retrieval; ties back to a tool_call and stores vendor response. (0 rows; fields: ['id', 'tool_call_id', 'workspace_id', 'task_kind', 'status', 'vendor_task_id', 'request_params', 'response_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: unique(tool_call_id)
  - constraint: fk(tool_call_id) references tool_calls(id) on delete cascade
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
- `keyword_and_page_tasks.json` — Normalized storage for keyword search volume jobs and page analysis jobs (content parsing + instant page audit). Stores target inputs and vendor responses per tool call. (19 rows; fields: ['id', 'tool_call_id', 'workspace_id', 'task_kind', 'status', 'vendor_task_id', 'target_url', 'keywords', 'request_params', 'response_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: unique(tool_call_id)
  - constraint: fk(tool_call_id) references tool_calls(id) on delete cascade
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: target_url is null or length(target_url) <= 2048

## Business rules enforced by the tools

- Each MCP tool invocation MUST create exactly one tool_calls row with tool_name set to the invoked tool and request_payload stored verbatim (currently always {}).
- A tool_calls row for tool_name in ['serp-organic-live-advanced','serp-organic-locations-list'] MUST have exactly one serp_tasks row linked by tool_call_id; other tools MUST have exactly one keyword_and_page_tasks row linked by tool_call_id.
- Tool execution MUST enforce workspace.status='active' and api_keys.status='active'; otherwise the call is rejected and tool_calls.status='failed' with an error_code indicating authorization failure.
- Before transitioning a tool call from queued->running, the system MUST ensure requests_used_month + 1 <= monthly_request_limit and (cost_usd_used_month + estimated_cost_usd) <= monthly_cost_usd_limit for the workspace; otherwise the call is rejected and recorded as failed due to quota_exceeded.
- When a tool call reaches a terminal state (succeeded/failed/cancelled), finished_at MUST be set and the corresponding task table status MUST match the terminal outcome (succeeded or failed; cancelled only applies to tool_calls).
- actual_cost_usd, when present, MUST be applied to workspaces.cost_usd_used_month (delta-adjust if estimated_cost_usd was pre-charged) and MUST be >= 0.
- serp-organic-locations-list results SHOULD be cached per workspace by reusing a recent serp_tasks row with task_kind='locations_list' and status='succeeded' created within a configured TTL; if reused, a new tool_calls row is still created but the serp_tasks row may reference the cached response via response_payload copy.
- FK integrity MUST be enforced: deleting a workspace cascades to api_keys, tool_calls, and all task rows; deleting an api_key is restricted if referenced by tool_calls.