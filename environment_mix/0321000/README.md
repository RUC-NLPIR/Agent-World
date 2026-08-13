# Cloudflare Playwright — local MCP environment

This backend stores ephemeral Playwright browser sessions for API clients, including tabs/pages, captured artifacts (snapshots, screenshots, PDFs), and observability telemetry (console logs, network requests). The main workflow is: a client session is created implicitly, operations mutate the active tab/page state, and artifacts/events are persisted for later retrieval until the session expires or is closed.

Repository: https://github.com/cloudflare/playwright-mcp
Homepage: https://smithery.ai/server/@cloudflare/playwright-mcp

## Datastore

- `api_keys.json` — API credentials used by clients to access the Playwright MCP service, including basic quotas/limits used to protect the browser fleet. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'quota_sessions_per_minute', 'quota_ops_per_minute', 'quota_max_session_seconds', 'quota_max_tabs', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: quota_sessions_per_minute BETWEEN 1 AND 600
  - constraint: quota_ops_per_minute BETWEEN 10 AND 6000
  - constraint: quota_max_session_seconds BETWEEN 5 AND 7200
- `browser_sessions.json` — An ephemeral Playwright browser context/session for one client. Tools operate against the currently active tab within an active session. (12 rows; fields: ['id', 'api_key_id', 'status', 'browser_channel', 'worker_region', 'installed_at', 'active_tab_id', 'default_viewport_width', 'default_viewport_height', 'last_activity_at', 'expires_at', 'closed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closing', 'closed', 'expired', 'failed']
  - constraint: default_viewport_width BETWEEN 200 AND 3840
  - constraint: default_viewport_height BETWEEN 200 AND 2160
  - constraint: expires_at > created_at
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
- `browser_tabs.json` — Tabs/pages within a browser session. Supports listing/selecting/closing and stores navigations and current URL/title. (12 rows; fields: ['id', 'session_id', 'tab_index', 'status', 'current_url', 'title', 'viewport_width', 'viewport_height', 'history_length', 'history_position', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['open', 'closing', 'closed', 'crashed']
  - constraint: unique(session_id, tab_index)
  - constraint: tab_index >= 0
  - constraint: viewport_width BETWEEN 200 AND 3840
  - constraint: viewport_height BETWEEN 200 AND 2160
- `browser_events.json` — Append-only telemetry/events captured from a tab: console messages, network requests, dialogs, and high-level tool invocations. (34 rows; fields: ['id', 'session_id', 'tab_id', 'event_type', 'severity', 'message', 'payload', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['console', 'network_request', 'dialog', 'tool_call']
  - constraint: fk(session_id) references browser_sessions(id) on delete cascade
  - constraint: fk(tab_id) references browser_tabs(id) on delete set null
  - constraint: occurred_at <= created_at
- `browser_artifacts.json` — Binary/serialized outputs generated from a tab: accessibility snapshots, screenshots, and PDFs. (34 rows; fields: ['id', 'session_id', 'tab_id', 'artifact_type', 'status', 'mime_type', 'byte_size', 'storage_url', 'content', 'screenshot_format', 'target_element', 'target_ref', 'created_at', 'updated_at', 'ready_at'])
  - lifecycle `status`: ['creating', 'ready', 'failed', 'deleted']
  - constraint: fk(session_id) references browser_sessions(id) on delete cascade
  - constraint: fk(tab_id) references browser_tabs(id) on delete cascade
  - constraint: byte_size >= 0
  - constraint: mime_type in ('application/pdf','image/jpeg','image/png','application/json')

## Business rules enforced by the tools

- All tool calls require an api_key in status='active'; otherwise reject.
- Each tool call must resolve to exactly one active browser_session in status='active'; if none exists, create one implicitly (implementation choice) but must still enforce api_keys quotas.
- browser_close sets browser_sessions.status from 'active' -> 'closing' -> 'closed', sets closed_at, and cascades tab closure by setting any open tabs to 'closing' -> 'closed'.
- browser_wait(time) requires 0 <= time <= 300; it updates browser_sessions.last_activity_at and records a browser_events row of event_type='tool_call' with payload.time.
- browser_resize(width,height) requires width and height integers within [200, 3840] and [200, 2160]; it updates the active tab viewport fields.
- browser_tab_new(url) creates a new browser_tabs row with next available tab_index; if url is provided it must be a valid absolute URL and becomes current_url after navigation completes.
- browser_tab_list returns browser_tabs for the session ordered by tab_index; only tabs with status in ('open','closing') are considered existing for index semantics.
- browser_tab_select(index) requires a tab with session_id and tab_index=index and status='open'; it sets browser_sessions.active_tab_id to that tab.
- browser_tab_close(index) closes the specified tab; if index is omitted it closes the active tab. After closure, if the active tab was closed, the service selects the lowest tab_index still open or sets active_tab_id to null if none remain.
- browser_navigate(url) requires a valid absolute URL; it updates active tab current_url and increments history_length and history_position accordingly; it also appends a browser_events row of type='network_request' for the main document request (at minimum).
- browser_navigate_back/forward require an active tab with sufficient history (history_position > 0 for back; history_position < history_length for forward); otherwise no-op or error per implementation, but must not corrupt history counters.
- browser_console_messages returns browser_events filtered by (session_id, active tab_id, event_type='console') ordered by occurred_at.
- browser_network_requests returns browser_events filtered by (session_id, active tab_id, event_type='network_request') ordered by occurred_at.
- browser_handle_dialog(accept,promptText) applies to the most recent unhandled dialog event for the active tab; it appends a 'tool_call' event with the decision and must reject promptText unless the dialog payload indicates type='prompt'.
- browser_click/hover/type/drag/select_option require both element and ref fields (and for type: text); they record a 'tool_call' event including provided element/ref and must only be allowed when session and active tab are status='open'.
- browser_type.submit and browser_type.slowly default to false when omitted; service records their effective boolean values in tool_call payload for reproducibility.
- browser_select_option.values must be a non-empty array with max length 100; service records the values array in the tool_call payload.
- browser_press_key(key) requires 1 <= length(key) <= 50 and records a tool_call event with payload.key.
- browser_take_screenshot(raw, element, ref) enforces that element and ref are provided together; it creates a browser_artifacts row with artifact_type='screenshot', screenshot_format='png' if raw=true else 'jpeg', transitions status creating->ready/failed, and stores storage_url/byte_size.
- browser_pdf_save creates a browser_artifacts row with artifact_type='pdf' and mime_type='application/pdf'; transitions creating->ready/failed and stores storage_url/byte_size.
- browser_snapshot creates a browser_artifacts row with artifact_type='accessibility_snapshot' and mime_type='application/json'; content must contain the serialized accessibility tree and status transitions creating->ready/failed.
- browser_file_upload(paths) requires 1..20 absolute paths and records a tool_call event with payload.paths; if the runtime cannot access the paths, the tool_call must fail and be recorded with severity='error'.
- browser_install sets browser_sessions.installed_at for the active session's worker image context and records a tool_call event; it is idempotent (repeated calls do not create duplicate installs).
- Quota enforcement: within any rolling 60s window per api_key_id, new sessions cannot exceed quota_sessions_per_minute and tool operations cannot exceed quota_ops_per_minute (tracked via counts of browser_sessions.created_at and browser_events where event_type='tool_call').
- No tool may operate on a tab whose status != 'open' or a session whose status != 'active'; attempts must error and record a tool_call event with severity='error' where possible.
- Retention: browser_events and browser_artifacts are eligible for deletion after browser_sessions.closed_at or expires_at + configured grace period; deleting artifacts must set status='deleted' before removing storage_url.