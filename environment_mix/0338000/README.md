# Playwright — local MCP environment

This backend stores Playwright-driven browser automation sessions and the ordered stream of tool invocations (navigate, content extraction, and pointer interactions) performed against pages within those sessions. The main workflow is: a client uses a session, navigates to a URL, then repeatedly captures content/interactive elements and issues mouse actions; the system logs each tool call with inputs/outputs for replay, debugging, and auditing.

Repository: https://github.com/showfive/playwright-mcp-server
Homepage: https://smithery.ai/server/@showfive/playwright-mcp-server

## Datastore

- `api_keys.json` — API credentials used to authenticate callers and enforce basic quotas/limits for Playwright automation. (24 rows; fields: ['id', 'key_hash', 'label', 'status', 'rate_limit_rpm', 'max_concurrent_sessions', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_rpm >= 1 and rate_limit_rpm <= 6000
  - constraint: max_concurrent_sessions >= 1 and max_concurrent_sessions <= 100
- `sessions.json` — A logical browser session (Playwright browser/context/page) associated with an API key; tool calls operate within an active session. (30 rows; fields: ['id', 'api_key_id', 'status', 'user_agent', 'viewport_width', 'viewport_height', 'current_page_id', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['active', 'closed', 'error']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(current_page_id) references pages(id) on delete set null
  - constraint: viewport_width is null or (viewport_width >= 100 and viewport_width <= 10000)
  - constraint: viewport_height is null or (viewport_height >= 100 and viewport_height <= 10000)
- `pages.json` — A navigated document/page within a session; content extraction tools read from the current page, and actions target coordinates relative to it. (34 rows; fields: ['id', 'session_id', 'status', 'url', 'final_url', 'title', 'http_status', 'dom_content_loaded_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['loading', 'ready', 'navigated', 'error']
  - constraint: fk(session_id) references sessions(id) on delete cascade
  - constraint: url like 'http%'
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
- `tool_invocations.json` — Append-only log of each tool call (echo, navigate, content reads, and mouse actions) including parameters, derived page context, and results/errors. (34 rows; fields: ['id', 'api_key_id', 'session_id', 'page_id', 'tool_name', 'status', 'input', 'output', 'error_message', 'duration_ms', 'sequence_no', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(session_id) references sessions(id) on delete set null
  - constraint: fk(page_id) references pages(id) on delete set null
  - constraint: unique(session_id, sequence_no) where session_id is not null
- `page_snapshots.json` — Materialized captures of page state returned by read tools: full HTML content, visible content extraction, and interactive element bounding boxes. (34 rows; fields: ['id', 'session_id', 'page_id', 'tool_invocation_id', 'snapshot_type', 'min_visible_percentage', 'content_html', 'content_text', 'interactive_elements', 'status', 'created_at', 'updated_at', 'expires_at'])
  - lifecycle `status`: ['created', 'stored', 'expired']
  - constraint: fk(session_id) references sessions(id) on delete cascade
  - constraint: fk(page_id) references pages(id) on delete cascade
  - constraint: fk(tool_invocation_id) references tool_invocations(id) on delete cascade
  - constraint: unique(tool_invocation_id)

## Business rules enforced by the tools

- All tool calls must authenticate with an api_keys row whose status is 'active'; otherwise the invocation is rejected and no session/page mutations occur.
- For each api_key_id, the number of sessions with status='active' must be <= api_keys.max_concurrent_sessions.
- The navigate tool must create a tool_invocations row with tool_name='navigate' and input.url set, then create or update a pages row for the session and set sessions.current_page_id to that page on success.
- get_all_content must record a tool_invocations row and persist a page_snapshots row with snapshot_type='all_content' and content_html populated for the current page.
- get_visible_content must accept minVisiblePercentage only in [0,100]; when provided it is stored into tool_invocations.input.minVisiblePercentage and page_snapshots.min_visible_percentage.
- get_interactive_elements must persist a page_snapshots row with snapshot_type='interactive_elements' and interactive_elements as an array of objects that include coordinates/bounds sufficient to drive mouse actions.
- move_mouse must record input.x and input.y as numbers in tool_invocations.input and must require an active session and a current page.
- mouse_click must validate button in {'left','right','middle'} when provided and must record clickCount when provided; clickCount must be >= 1 and <= 10.
- mouse_wheel must require deltaY and may accept deltaX; both are stored in tool_invocations.input and must be finite numbers; deltaY must be non-zero.
- drag_and_drop must require sourceX, sourceY, targetX, targetY; all stored in tool_invocations.input and must be finite numbers.
- For any tool invocation with status='succeeded', tool_invocations.output may be stored but tool-specific persisted artifacts must be in page_snapshots for read tools; for status='failed', error_message must be non-null.
- sequence_no for tool_invocations must increase monotonically within a session; concurrent writers must allocate sequence_no atomically to preserve unique(session_id, sequence_no).
- A page_snapshots row must reference a succeeded tool_invocations row; snapshots cannot be created for failed invocations.