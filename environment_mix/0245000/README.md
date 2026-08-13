# Toolbox — local MCP environment

This backend stores an MCP server registry (servers and their tool manifests) and supports hybrid search over server metadata. It also records and executes tool invocations against a selected server, tracking request/response payloads, status, and basic abuse/quota limits.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@smithery/toolbox

## Datastore

- `mcp_servers.json` — Registry of MCP servers discoverable via search and addressable via qualifiedName. (21 rows; fields: ['id', 'qualified_name', 'display_name', 'description', 'categories', 'tags', 'repository_url', 'homepage_url', 'icon_url', 'endpoint_url', 'auth_type', 'auth_config', 'popularity_score', 'search_document', 'status', 'published_at', 'last_indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'deprecated', 'disabled']
  - constraint: unique(qualified_name)
  - constraint: endpoint_url is required when status in ('published','deprecated')
  - constraint: popularity_score >= 0
  - constraint: array_length(categories) <= 20
- `mcp_server_tools.json` — Tool manifest entries exposed by each MCP server; used to validate use_tool requests and show capabilities in registry responses. (11 rows; fields: ['id', 'server_id', 'name', 'description', 'input_schema', 'output_schema', 'is_enabled', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: foreign key(server_id) references mcp_servers(id) on delete cascade
  - constraint: unique(server_id, name)
  - constraint: is_enabled = false implies status in ('disabled') or status = 'deprecated'
- `search_queries.json` — Audit log of search requests, used for analytics, abuse detection, and to tune hybrid ranking. (18 rows; fields: ['id', 'query_text', 'n_requested', 'n_returned', 'hybrid_config', 'request_fingerprint', 'created_at', 'updated_at'])
  - constraint: query_text length between 1 and 2000
  - constraint: n_requested between 1 and 5
  - constraint: n_returned between 0 and 5
  - constraint: n_returned <= n_requested
- `search_results.json` — Per-search ranked results returned to the caller; supports debugging ranking and offline evaluation. (18 rows; fields: ['id', 'search_id', 'server_id', 'rank', 'score', 'score_breakdown', 'created_at', 'updated_at'])
  - constraint: foreign key(search_id) references search_queries(id) on delete cascade
  - constraint: foreign key(server_id) references mcp_servers(id) on delete restrict
  - constraint: unique(search_id, rank)
  - constraint: unique(search_id, server_id)
- `tool_invocations.json` — Record of executing a tool on a specific MCP server, including request/response payloads, timings, and status. (19 rows; fields: ['id', 'server_id', 'tool_id', 'qualified_name', 'tool_name', 'arguments', 'response', 'error', 'status', 'upstream_request_id', 'http_status', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out']
  - constraint: foreign key(server_id) references mcp_servers(id) on delete restrict
  - constraint: foreign key(tool_id) references mcp_server_tools(id) on delete set null
  - constraint: qualified_name must equal (select qualified_name from mcp_servers where id = server_id)
  - constraint: tool_name length between 1 and 200

## Business rules enforced by the tools

- search_servers(query, n): insert a row into search_queries with query_text=query and n_requested=coalesce(n,3); enforce 1 <= n_requested <= 5; only return servers where mcp_servers.status='published'.
- Hybrid search must rank against mcp_servers.search_document plus structured boosts from tags/categories/popularity_score; for each returned server insert one search_results row with rank starting at 1 and rank <= n_requested.
- use_tool(qualifiedName, parameters.name, parameters.arguments): resolve mcp_servers by qualified_name; reject if not found or mcp_servers.status in ('disabled','draft').
- For use_tool: resolve tool definition by (server_id, tool_name); if found, reject if mcp_server_tools.status='disabled' or is_enabled=false; if not found, either reject or record invocation with tool_id=null according to policy, but must still store tool_name and arguments.
- Each tool invocation must be recorded in tool_invocations: create with status='queued' then transition through allowed lifecycle transitions only; on completion set exactly one of response or error and move to a terminal status (succeeded/failed/cancelled/timed_out).
- Arguments payload size must be limited (e.g., serialized JSON <= 256KB) and must validate against mcp_server_tools.input_schema when present; otherwise accept arbitrary object.
- mcp_servers.qualified_name must be globally unique and immutable once status is 'published' (updates must create a new server record if rename is required).
- Deleting a server must be blocked if it has any tool_invocations; instead set mcp_servers.status='disabled'.
- Search and invocation rate limiting/quota enforcement should be based on request_fingerprint or an external API key identity; when limits are exceeded, the system must not create tool_invocations and should still optionally log search_queries with n_returned=0.