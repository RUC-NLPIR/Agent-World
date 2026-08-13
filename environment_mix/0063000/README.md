# Toolbox (Preview) — local MCP environment

This backend stores a registry of Model Context Protocol (MCP) servers and their available tools, plus operational logs of search queries and tool executions. Main workflows are (1) hybrid-searching the registry to return top N servers and (2) executing a named tool on a selected server while recording the request/response lifecycle, errors, and latency.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@smithery-ai/toolbox-dev

## Datastore

- `mcp_servers.json` — Canonical registry entries for MCP servers (what users search over and select via qualifiedName). (17 rows; fields: ['id', 'qualified_name', 'display_name', 'description', 'homepage_url', 'repo_url', 'transport', 'endpoint_url', 'tags', 'owner', 'icon_url', 'status', 'last_indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'deprecated', 'disabled']
  - constraint: unique(qualified_name)
  - constraint: display_name <> ''
  - constraint: description <> ''
  - constraint: transport IN ('stdio','http','sse','websocket','unknown')
- `mcp_tools.json` — Tools exposed by each MCP server; used to validate/route use_tool(name, arguments). (18 rows; fields: ['id', 'server_id', 'name', 'description', 'input_schema', 'output_schema', 'is_streaming', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: foreign_key(server_id) references mcp_servers(id) on delete cascade
  - constraint: unique(server_id, name)
  - constraint: name <> ''
  - constraint: status IN ('active','deprecated','disabled')
- `search_queries.json` — Log of search_servers calls including hybrid search parameters and returned result ids for audit/analytics. (18 rows; fields: ['id', 'query', 'n', 'search_mode', 'status', 'result_server_ids', 'latency_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: query <> ''
  - constraint: n >= 1 AND n <= 5
  - constraint: search_mode = 'hybrid'
  - constraint: status IN ('received','running','succeeded','failed')
- `tool_executions.json` — Audit log of use_tool calls, capturing routing by qualifiedName, tool name, arguments, and responses. (21 rows; fields: ['id', 'server_id', 'qualified_name', 'tool_id', 'tool_name', 'arguments', 'status', 'request_started_at', 'request_finished_at', 'latency_ms', 'response', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign_key(server_id) references mcp_servers(id)
  - constraint: foreign_key(tool_id) references mcp_tools(id)
  - constraint: qualified_name <> ''
  - constraint: tool_name <> ''

## Business rules enforced by the tools

- search_servers must persist a search_queries row with query exactly as provided and n set to provided value or default 3 when omitted.
- search_servers must reject any n > 5 or n < 1 (schema max 5), and must not return more than n results.
- search_servers must only return servers with mcp_servers.status = 'active'; deprecated servers may be optionally included only if explicitly allowed by internal policy (default exclude).
- use_tool must resolve qualifiedName by exact match against mcp_servers.qualified_name; if not found or server.status != 'active', the execution must be recorded as failed with error_code in ('SERVER_NOT_FOUND','SERVER_DISABLED').
- use_tool must record a tool_executions row for every call; status transitions must follow the declared lifecycle and request_started_at/request_finished_at must be consistent with status.
- use_tool.parameters.name must match an active tool in mcp_tools for the resolved server; if missing, record failed with error_code = 'TOOL_NOT_FOUND'.
- If mcp_tools.input_schema is present for the resolved tool, use_tool.arguments must validate against it; otherwise allow any object. Validation failures must be recorded with error_code = 'INVALID_ARGUMENTS'.
- tool_executions.tool_id must be non-null when the tool was found; if tool_id is set it must belong to the same server_id (enforceable via application-level check).
- mcp_servers.qualified_name is immutable after activation (status transitions to active lock qualified_name), to keep use_tool routing stable; changes require creating a new server row and deprecating the old one.