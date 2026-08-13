# Browser Use MCP Server — local MCP environment

This backend stores stateful, scriptable browser sessions used by an MCP server to navigate pages, manage tabs, perform user-like interactions (click, type, select, hover, scroll, keypress), and extract page content (text/markdown/links/clickables) as well as artifacts (screenshots, downloads). The main workflow is: create/attach to a live browser session, mutate its current tab/page via actions, and persist action results and generated artifacts for later retrieval and debugging/auditing.

Repository: https://github.com/bytedance/UI-TARS-desktop
Homepage: https://smithery.ai/server/@bytedance/mcp-server-browser

## Datastore

- `browser_sessions.json` — A logical browser instance lifecycle owned by a client connection (or task) that can have multiple tabs and produces downloads/screenshots. Supports browser_close. (12 rows; fields: ['id', 'client_connection_id', 'browser_engine', 'headless', 'locale', 'timezone', 'active_tab_id', 'status', 'last_error', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['starting', 'ready', 'closing', 'closed', 'error']
  - constraint: active_tab_id references browser_tabs.id and browser_tabs.session_id must equal this session id (enforce via trigger/constraint)
  - constraint: created_at <= updated_at
  - constraint: closed_at is not null iff status in ('closed')
- `browser_tabs.json` — Tabs within a browser session. Supports browser_tab_list, browser_new_tab, browser_switch_tab, browser_close_tab, and holds navigation history used by back/forward. (17 rows; fields: ['id', 'session_id', 'tab_index', 'title', 'current_url', 'history_cursor', 'status', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['open', 'closing', 'closed', 'crashed']
  - constraint: unique(session_id, tab_index)
  - constraint: tab_index >= 0
  - constraint: history_cursor >= -1
  - constraint: session_id must reference an existing browser_sessions row
- `tab_navigations.json` — Ordered navigation history entries per tab. Used to implement browser_navigate, browser_go_back, browser_go_forward, and to record resulting page metadata/state. (33 rows; fields: ['id', 'session_id', 'tab_id', 'history_index', 'request_url', 'final_url', 'referrer', 'http_status', 'title', 'dom_content_loaded_at', 'load_event_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['requested', 'committed', 'completed', 'failed']
  - constraint: unique(tab_id, history_index)
  - constraint: history_index >= 0
  - constraint: http_status between 100 and 599 when not null
  - constraint: tab_id must reference browser_tabs.id and session_id must equal browser_tabs.session_id (enforce via trigger/constraint)
- `page_state_snapshots.json` — Cached page-derived outputs and element indexes for a given tab at a point in time. Supports browser_get_text, browser_get_markdown, (deprecated) browser_get_html, browser_read_links, browser_get_clickable_elements, and provides the element index space used by browser_click/hover/select/form_input_fill/screenshot selector/index. (35 rows; fields: ['id', 'session_id', 'tab_id', 'navigation_id', 'url', 'title', 'html', 'text', 'markdown', 'links', 'clickable_elements', 'clickables_version', 'status', 'error_message', 'captured_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['capturing', 'ready', 'stale', 'failed']
  - constraint: clickables_version >= 0
  - constraint: tab_id must reference browser_tabs.id and session_id must equal browser_tabs.session_id (enforce via trigger/constraint)
  - constraint: navigation_id is null or (navigation_id references tab_navigations.id and tab_navigations.tab_id = tab_id)
  - constraint: captured_at is not null iff status='ready'
- `browser_artifacts.json` — Binary/large artifacts created during a session, including screenshots and downloaded files. Supports browser_screenshot and browser_get_download_list. (21 rows; fields: ['id', 'session_id', 'tab_id', 'kind', 'name', 'source_url', 'mime_type', 'byte_size', 'storage_backend', 'storage_key', 'sha256', 'screenshot_params', 'download_filename', 'download_state', 'status', 'error_message', 'created_at', 'updated_at', 'available_at'])
  - lifecycle `status`: ['creating', 'available', 'failed', 'deleted']
  - constraint: byte_size is null or byte_size >= 0
  - constraint: kind='download' implies download_state is not null
  - constraint: kind='screenshot' implies screenshot_params is not null
  - constraint: storage_backend in ('local_fs','s3_compatible','inline_base64')
- `browser_actions.json` — Append-only audit log of tool invocations and their outcomes. Covers click/type/select/hover/scroll/press_key/evaluate/navigate/tab operations and ties to snapshots/artifacts produced. (35 rows; fields: ['id', 'session_id', 'tab_id', 'tool_name', 'input', 'result', 'related_navigation_id', 'related_snapshot_id', 'related_artifact_id', 'duration_ms', 'status', 'error_message', 'created_at', 'updated_at', 'started_at', 'finished_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: tab_id is null or (tab_id references browser_tabs.id and browser_tabs.session_id=session_id)
  - constraint: error_message is not null iff status='failed'
  - constraint: started_at is not null iff status in ('running','succeeded','failed','cancelled')

## Business rules enforced by the tools

- All tools operate against the currently active session and active tab; browser_sessions.status must be 'ready' for any tool except browser_close.
- browser_new_tab(url) creates a browser_tabs row with next available tab_index for the session, sets it as browser_sessions.active_tab_id, and inserts a tab_navigations row at history_index=0 with request_url=url.
- browser_switch_tab(index) requires an open tab with browser_tabs.tab_index=index in the same session; on success sets browser_sessions.active_tab_id to that tab.
- browser_close_tab closes only the active tab; it transitions browser_tabs.status open->closing->closed and selects a new active_tab_id if other open tabs exist, otherwise browser_sessions.active_tab_id becomes null.
- browser_navigate(url) appends a new tab_navigations record at history_index=history_cursor+1 and truncates any forward history (delete or mark unreachable entries with history_index > new cursor). It updates browser_tabs.current_url and increments history_cursor.
- browser_go_back requires browser_tabs.history_cursor > 0; it decrements history_cursor and updates browser_tabs.current_url/title based on the referenced tab_navigations entry.
- browser_go_forward requires browser_tabs.history_cursor < max(history_index) for the tab; it increments history_cursor and updates browser_tabs.current_url/title accordingly.
- browser_get_clickable_elements must create (or refresh) a page_state_snapshots row for the active tab with clickable_elements populated and clickables_version incremented versus the last ready snapshot for that tab.
- browser_click(index), browser_hover(index), browser_select(index,value), browser_form_input_fill(index,value) require that a ready snapshot exists for the tab and that index is within the latest snapshot.clickable_elements indices; otherwise the action fails with a guidance error to call browser_get_clickable_elements.
- browser_form_input_fill and browser_select require exactly one of (index, selector) to be provided; browser_hover requires exactly one of (index, selector); violations fail validation before execution.
- browser_screenshot may target either (selector) or (index) or neither (full page/viewport). If index is provided, it must be valid against the latest ready snapshot clickable_elements index space; the created browser_artifacts.kind='screenshot' must store screenshot_params mirroring input (name, selector, index, width, height, fullPage, highlight).
- browser_scroll(amount) defaults to scrolling to bottom when amount is null; when provided, amount must be between -200000 and 200000 inclusive (service-side safety limit).
- browser_press_key(key) must be either one of the enumerated special keys or a single Unicode grapheme; otherwise validation fails.
- browser_evaluate(script) executes in the context of the active tab; script length must be <= 200000 characters (service-side safety limit).
- browser_get_text/browser_get_markdown/browser_get_html/browser_read_links create or reuse a ready page_state_snapshots row for the active tab, returning the corresponding field; browser_get_html reads from page_state_snapshots.html and is marked deprecated but still supported.
- browser_get_download_list returns browser_artifacts rows where kind='download' and session_id matches, ordered by created_at desc; only artifacts with status in ('available','failed') are returned to clients by default.
- browser_close transitions browser_sessions.status to closing then closed, closes all open tabs, and prevents further tool execution for that session.