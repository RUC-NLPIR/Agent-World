# Playwright Automation Server — local MCP environment

This backend stores long-lived Playwright browser sessions, including navigation/page state metadata, codegen recording sessions, and the full audit trail of automation actions executed through the API tools. It also persists artifacts (screenshots/PDF/test output), console logs, and asynchronous network-response wait handles used by expect/assert response workflows.

Repository: https://github.com/adalovu/mcp-playwright
Homepage: https://smithery.ai/server/@adalovu/mcp-playwright

## Datastore

- `browser_sessions.json` — A server-managed Playwright browser context/session used by all playwright_* tools. Stores configuration (browser type, viewport, headless, UA) and the currently active tab/page pointer for actions like click/fill/evaluate. (18 rows; fields: ['id', 'status', 'browser_type', 'headless', 'viewport_width', 'viewport_height', 'default_timeout_ms', 'user_agent', 'current_url', 'active_tab_id', 'last_error', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['active', 'closing', 'closed', 'errored']
  - constraint: viewport_width BETWEEN 100 AND 10000
  - constraint: viewport_height BETWEEN 100 AND 10000
  - constraint: default_timeout_ms IS NULL OR default_timeout_ms BETWEEN 0 AND 600000
  - constraint: active_tab_id IS NULL OR (active_tab_id REFERENCES tabs.id AND tabs.session_id = browser_sessions.id)
- `tabs.json` — Tabs/pages belonging to a browser session. Enables tools like click_and_switch_tab and tracks per-tab navigation history and page content snapshots for get_visible_html/text. (18 rows; fields: ['id', 'session_id', 'status', 'is_active', 'current_url', 'title', 'history_index', 'history', 'last_visible_text', 'last_visible_html', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['open', 'closing', 'closed']
  - constraint: FK(session_id) REFERENCES browser_sessions.id ON DELETE CASCADE
  - constraint: history_index >= 0
  - constraint: history IS NOT NULL
  - constraint: is_active IN (true,false)
- `codegen_sessions.json` — Code generation sessions used to record Playwright actions and emit a generated test file. Supports start/get/end/clear flows and stores options/output metadata. (19 rows; fields: ['id', 'status', 'session_id', 'output_path', 'test_name_prefix', 'include_comments', 'recorded_actions', 'generated_test_file_path', 'generated_source', 'last_error', 'created_at', 'updated_at', 'ended_at'])
  - lifecycle `status`: ['recording', 'ended', 'cleared', 'errored']
  - constraint: output_path LIKE '/%'
  - constraint: test_name_prefix <> ''
  - constraint: recorded_actions IS NOT NULL
  - constraint: include_comments IN (true,false)
- `automation_events.json` — Append-only audit log of every Playwright tool invocation and its outcome. Stores parameters (selectors/url/etc), execution timing, and responses/errors for debugging and compliance. (18 rows; fields: ['id', 'session_id', 'tab_id', 'codegen_session_id', 'tool_name', 'status', 'request_params', 'result', 'error', 'duration_ms', 'created_at', 'updated_at'])
  - constraint: tool_name <> ''
  - constraint: request_params IS NOT NULL
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: FK(session_id) REFERENCES browser_sessions.id ON DELETE SET NULL
- `artifacts.json` — Binary/large output artifacts produced by actions: screenshots (optionally base64) and PDFs, plus generated test files metadata. Artifacts are linked to the event that produced them for traceability. (18 rows; fields: ['id', 'session_id', 'tab_id', 'event_id', 'codegen_session_id', 'kind', 'name', 'content_type', 'storage_mode', 'base64_data', 'file_path', 'byte_size', 'metadata', 'created_at', 'updated_at'])
  - constraint: FK(event_id) REFERENCES automation_events.id ON DELETE CASCADE
  - constraint: FK(session_id) REFERENCES browser_sessions.id ON DELETE SET NULL
  - constraint: FK(tab_id) REFERENCES tabs.id ON DELETE SET NULL
  - constraint: FK(codegen_session_id) REFERENCES codegen_sessions.id ON DELETE SET NULL
- `network_waits.json` — Tracks asynchronous response wait handles created by playwright_expect_response and later asserted by playwright_assert_response. Stores matching criteria, completion state, and captured response body/status for validation. (19 rows; fields: ['id', 'session_id', 'client_handle_id', 'status', 'url_pattern', 'matched_url', 'response_status', 'response_headers', 'response_body', 'expected_body_substring', 'assertion_passed', 'created_at', 'updated_at', 'matched_at', 'asserted_at'])
  - lifecycle `status`: ['pending', 'matched', 'asserted', 'timed_out', 'cancelled', 'errored']
  - constraint: FK(session_id) REFERENCES browser_sessions.id ON DELETE CASCADE
  - constraint: client_handle_id <> ''
  - constraint: url_pattern <> ''
  - constraint: UNIQUE(session_id, client_handle_id)

## Business rules enforced by the tools

- All playwright_* page interaction tools (navigate/click/fill/select/hover/drag/press_key/evaluate/go_back/go_forward/click_and_switch_tab/get_visible_text/get_visible_html/screenshot/save_as_pdf/console_logs/custom_user_agent/close) must operate on exactly one active browser_sessions row with status='active'; if no active session exists, the implementation must create one implicitly or return an error consistently (one policy chosen and enforced).
- playwright_navigate must set browser_sessions.browser_type/headless/viewport_width/viewport_height/default_timeout_ms when provided and update tabs.current_url + browser_sessions.current_url; if no tab exists, it must create an initial tabs row and mark it active.
- playwright_click_and_switch_tab must create a new tabs row when a new tab is detected, set it is_active=true, and set the prior active tab to is_active=false; browser_sessions.active_tab_id must be updated accordingly.
- playwright_go_back and playwright_go_forward must update tabs.history_index within bounds [0, len(history)-1]; out-of-range navigation attempts must be rejected or no-op deterministically.
- playwright_get_visible_text and playwright_get_visible_html must update tabs.last_visible_text/last_visible_html respectively and also record an automation_events row capturing the returned data (possibly truncated) in automation_events.result.
- playwright_screenshot must create an artifacts row with kind='screenshot' linked to the generating automation_events row. If storeBase64=true then artifacts.storage_mode='base64_inline' and artifacts.base64_data is required; if savePng=true then artifacts.storage_mode='file_path' and artifacts.file_path is required; both cannot be true simultaneously unless the implementation stores two artifacts.
- playwright_save_as_pdf must create an artifacts row with kind='pdf', storage_mode='file_path', and file_path under outputPath; filename defaults to 'page.pdf' if not provided; metadata must store format/printBackground/margin/outputPath/filename.
- playwright_console_logs must append console entries into automation_events.result and, if clear=true, must also clear the in-memory log buffer while still persisting the retrieval event; the filter parameters (type/search/limit/clear) must be stored in automation_events.request_params.
- HTTP client tools (playwright_get/post/put/patch/delete) must log an automation_events row with tool_name and request_params including url, value (when applicable), token, and headers. Sensitive fields (token, Authorization headers) must be redacted in persisted request_params.
- playwright_expect_response must upsert a network_waits row uniquely by (session_id, client_handle_id) only when the existing row is in a terminal state; otherwise it must fail to prevent overwriting an in-flight wait.
- playwright_assert_response must locate network_waits by (session_id, client_handle_id); it may only transition status from 'matched' to 'asserted' (or from 'pending' to terminal error/timeout based on internal waiting behavior). If value is provided, expected_body_substring must be saved and assertion_passed must reflect substring containment on the captured response_body.
- end_codegen_session may only be called when codegen_sessions.status='recording'; it must transition to 'ended' and set generated_test_file_path and/or generated_source; clear_codegen_session may only be called when status='recording' and must transition to 'cleared' without generating output.
- If a codegen session is active and bound to a browser session, then all page interaction events executed in that browser session must also be linked to codegen_sessions via automation_events.codegen_session_id and appended (normalized) into codegen_sessions.recorded_actions.
- playwright_close must transition browser_sessions.status from 'active' to 'closing' to 'closed', set closed_at, and mark all open tabs as closed; subsequent tool invocations against a closed session must be rejected.