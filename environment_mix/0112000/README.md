# Playwright Browser Automation Server — local MCP environment

This backend stores long-lived browser automation sessions (Playwright browser + contexts + tabs/pages) and an append-only event log of all user-invoked tools and observed browser outputs (console, network, dialogs, snapshots). The primary workflow is: create/attach to a session, navigate and interact with a page across tabs, capture artifacts (snapshots/screenshots/pdfs), and finally close tabs/pages/sessions while retaining a replayable audit trail.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@JOBKO-QA/playwright-mcp-private

## Datastore

- `automation_sessions.json` — Represents a logical Playwright automation session bound to a single client/API key. Holds session lifecycle, runtime configuration and the currently selected tab/page. (18 rows; fields: ['id', 'client_key_id', 'browser_engine', 'headless', 'viewport_width', 'viewport_height', 'current_tab_id', 'status', 'last_error', 'last_activity_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closing', 'closed', 'errored']
  - constraint: viewport_width IS NULL OR (viewport_width BETWEEN 100 AND 10000)
  - constraint: viewport_height IS NULL OR (viewport_height BETWEEN 100 AND 10000)
  - constraint: last_activity_at >= created_at
  - constraint: current_tab_id IS NULL OR current_tab_id references browser_tabs.id AND browser_tabs.session_id = automation_sessions.id
- `browser_tabs.json` — Represents an open tab/page within a session. Supports tab listing, selection by index, navigation history metadata and closure. (17 rows; fields: ['id', 'session_id', 'tab_index', 'title', 'current_url', 'can_go_back', 'can_go_forward', 'status', 'opened_at', 'closed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'closing', 'closed', 'crashed']
  - constraint: unique(session_id, tab_index)
  - constraint: tab_index >= 0
  - constraint: closed_at IS NULL OR closed_at >= opened_at
  - constraint: session_id references automation_sessions.id ON DELETE CASCADE
- `tool_invocations.json` — Append-only log of every tool call (the 25 tools) with parameters, execution timing, success/failure and links to produced artifacts. This enables debugging, replay, rate-limiting and auditability. (18 rows; fields: ['id', 'session_id', 'tab_id', 'tool_name', 'input', 'status', 'started_at', 'ended_at', 'duration_ms', 'error_message', 'result', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: session_id references automation_sessions.id ON DELETE CASCADE
  - constraint: tab_id IS NULL OR (tab_id references browser_tabs.id AND browser_tabs.session_id = tool_invocations.session_id)
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: ended_at IS NULL OR started_at IS NOT NULL
- `page_observations.json` — Time-series observations emitted from the page during a session/tab: console messages, network requests, dialogs, and accessibility snapshots. Read tools query these records. (18 rows; fields: ['id', 'session_id', 'tab_id', 'invocation_id', 'kind', 'occurred_at', 'payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'redacted', 'deleted']
  - constraint: session_id references automation_sessions.id ON DELETE CASCADE
  - constraint: tab_id references browser_tabs.id ON DELETE CASCADE
  - constraint: browser_tabs.session_id = page_observations.session_id (enforced via FK or trigger)
  - constraint: kind='accessibility_snapshot' implies payload contains refs needed for element ref targeting
- `artifacts.json` — Binary outputs produced by tools (screenshots and PDFs) plus generated test files. Supports saving to disk or object storage with metadata and linkage to the producing invocation. (18 rows; fields: ['id', 'session_id', 'tab_id', 'invocation_id', 'artifact_type', 'filename', 'content_type', 'byte_size', 'storage_backend', 'storage_uri', 'sha256', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['writing', 'available', 'deleted', 'failed']
  - constraint: session_id references automation_sessions.id ON DELETE CASCADE
  - constraint: invocation_id references tool_invocations.id ON DELETE CASCADE
  - constraint: byte_size >= 0
  - constraint: unique(session_id, filename, created_at) (pragmatic de-dupe within a session)
- `client_keys.json` — Optional multi-tenant authentication and quota control. Even if not exposed as a tool, production deployments commonly require API keys for metering and isolation. (18 rows; fields: ['id', 'key_hash', 'label', 'status', 'daily_session_limit', 'daily_invocation_limit', 'daily_artifact_bytes_limit', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_session_limit IS NULL OR daily_session_limit >= 0
  - constraint: daily_invocation_limit IS NULL OR daily_invocation_limit >= 0
  - constraint: daily_artifact_bytes_limit IS NULL OR daily_artifact_bytes_limit >= 0

## Business rules enforced by the tools

- All tools operate against automation_sessions.current_tab_id unless explicitly tab-targeting; if current_tab_id is null, tools that require a page MUST fail with a deterministic error (e.g., 'no active tab').
- browser_tab_new inserts a browser_tabs row with next tab_index = (max(tab_index)+1) within the session, status='open', and if it's the first tab or if server policy is 'auto_select_new_tab', updates automation_sessions.current_tab_id to the new tab.
- browser_tab_list returns browser_tabs for the session ordered by tab_index where status in ('open','closing') (or include closed if configured), mapping directly from browser_tabs fields.
- browser_tab_select requires input.index to exist and match an open tab_index for that session; it updates automation_sessions.current_tab_id to the corresponding browser_tabs.id.
- browser_tab_close closes the specified index if provided; otherwise closes the current tab. It transitions browser_tabs.status open->closing->closed and sets closed_at; if closing the current tab, automation_sessions.current_tab_id MUST be updated to another open tab (lowest index) or NULL if none remain.
- browser_close closes the current page/tab (same semantics as browser_tab_close with no index). If no tabs remain, the session may remain active (idle) or transition to closing based on server configuration; in all cases the invocation is logged.
- browser_resize updates automation_sessions.viewport_width/viewport_height and logs the invocation; width/height must be within configured bounds.
- browser_navigate/browser_navigate_back/browser_navigate_forward update browser_tabs.current_url (and can_go_back/can_go_forward) after the Playwright action completes; navigation actions MUST be rejected for tabs not in status='open'.
- browser_snapshot creates a page_observations row with kind='accessibility_snapshot' containing the refs used later by element/ref tools (browser_click/hover/type/select_option/drag/take_screenshot with ref).
- browser_console_messages returns page_observations.kind='console_message' for the current tab ordered by occurred_at; the server may cap results (e.g., last 500) and should document truncation in the tool_invocations.result.
- browser_network_requests returns page_observations.kind='network_request' for the current tab since last navigation OR since tab opened; if 'since navigation' is implemented, the cutoff timestamp is stored in tool_invocations.result for the last navigate event and used as a filter.
- browser_handle_dialog records a page_observations row kind='dialog' when the dialog appears; handling a dialog creates a corresponding tool_invocations row and may update the dialog observation payload with outcome (accepted/dismissed, promptText).
- browser_file_upload and browser_type/browser_select_option/browser_click/browser_hover/browser_drag/browser_press_key/browser_wait_for must validate required parameters per tool schema and record them exactly in tool_invocations.input; if element/ref pairs are provided, they must correspond to the latest accessibility snapshot refs or the call fails.
- browser_take_screenshot creates an artifacts row with artifact_type determined by input.raw (png if raw=true else jpeg), filename defaulting per spec if absent; if element/ref provided, both must be provided and are stored in tool_invocations.input.
- browser_pdf_save creates an artifacts row with artifact_type='pdf' and a default filename if absent; PDFs may only be generated for open tabs.
- browser_generate_playwright_test creates an artifacts row with artifact_type='playwright_test' (content_type 'text/plain' or 'application/typescript') and stores the generated content location; required fields name/description/steps must be non-empty and steps must have length >= 1.
- If client_keys are enabled, any request with a disabled/revoked key MUST be rejected; for active keys the server enforces daily_session_limit/daily_invocation_limit/daily_artifact_bytes_limit by counting rows in automation_sessions/tool_invocations/artifacts for that key within the current day in server timezone.