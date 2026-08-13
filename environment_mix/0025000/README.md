# BrowserTools — local MCP environment

BrowserTools stores per-browser-session telemetry (console + network logs), lightweight artifacts (screenshots, selected element snapshots), and on-demand Lighthouse-style audit runs (accessibility, performance, SEO, best-practices, Next.js). The main workflows are: ingest logs during a live session, read and filter them via API, wipe them from memory, and trigger audits/modes that produce persisted results tied to the active page.

Repository: https://github.com/diulela/browser-tools-mcp
Homepage: https://smithery.ai/server/@diulela/browser-tools-mcp

## Datastore

- `browser_sessions.json` — Represents a connected browser instance/session that produces logs and can run audits against its current active tab/page. (18 rows; fields: ['id', 'status', 'started_at', 'ended_at', 'current_url', 'current_title', 'user_agent', 'viewport', 'last_seen_at', 'log_buffer_bytes', 'log_buffer_limit_bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closed', 'expired']
  - constraint: log_buffer_bytes >= 0
  - constraint: log_buffer_limit_bytes >= 1048576
  - constraint: log_buffer_bytes <= log_buffer_limit_bytes
  - constraint: ended_at is null when status = 'active'
- `browser_logs.json` — Append-only console and network log events captured from a browser session. (18 rows; fields: ['id', 'session_id', 'source', 'level', 'event_type', 'message', 'timestamp', 'url', 'http_method', 'http_status', 'request_id', 'initiator', 'duration_ms', 'payload', 'created_at', 'updated_at'])
  - lifecycle `level`: ['debug', 'info', 'warning', 'error']
  - constraint: fk(session_id) references browser_sessions(id) on delete cascade
  - constraint: timestamp is required
  - constraint: http_status between 100 and 599 when not null
  - constraint: duration_ms >= 0 when not null
- `page_artifacts.json` — Persisted artifacts captured from the current page: screenshots and selected element snapshots. (19 rows; fields: ['id', 'session_id', 'artifact_type', 'status', 'page_url', 'mime_type', 'byte_size', 'storage_backend', 'storage_key', 'inline_base64', 'element_selector', 'element_snapshot', 'error_message', 'captured_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['capturing', 'available', 'failed', 'deleted']
  - constraint: fk(session_id) references browser_sessions(id) on delete cascade
  - constraint: byte_size >= 0 when not null
  - constraint: captured_at is not null when status = 'available'
  - constraint: error_message is not null when status = 'failed'
- `audit_runs.json` — Represents a single audit execution against the current page (Lighthouse-style categories plus Next.js). (18 rows; fields: ['id', 'session_id', 'audit_type', 'status', 'page_url', 'started_at', 'finished_at', 'score', 'summary', 'report', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(session_id) references browser_sessions(id) on delete cascade
  - constraint: score between 0 and 1 when not null
  - constraint: finished_at >= started_at when both not null
  - constraint: started_at is not null when status in ('running','succeeded','failed','cancelled')
- `session_modes.json` — Tracks mode toggles/requests such as debugger mode and audit mode for a browser session. (18 rows; fields: ['id', 'session_id', 'mode_type', 'status', 'details', 'error_message', 'requested_at', 'effective_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['requested', 'enabled', 'disabled', 'failed']
  - constraint: fk(session_id) references browser_sessions(id) on delete cascade
  - constraint: error_message is not null when status='failed'
  - constraint: unique(session_id, mode_type, status) where status='enabled'

## Business rules enforced by the tools

- All read tools (getConsoleLogs/getConsoleErrors/getNetworkLogs/getNetworkErrors) query browser_logs by the current active browser_sessions.id; 'errors' tools filter level='error' and source accordingly.
- wipeLogs deletes (or marks deleted via hard delete) all browser_logs for the active session and resets browser_sessions.log_buffer_bytes to 0 in the same transaction.
- takeScreenshot creates a page_artifacts row with artifact_type='screenshot' and status='capturing', then transitions to 'available' with stored payload pointer or inline_base64; on failure transitions to 'failed' with error_message.
- getSelectedElement creates (or returns latest) page_artifacts row with artifact_type='selected_element' and status='available' containing element_snapshot; if no element is selected it creates a 'failed' artifact with error_message describing the condition.
- runAccessibilityAudit/runPerformanceAudit/runSEOAudit/runBestPracticesAudit/runNextJSAudit each enqueue an audit_runs row with the matching audit_type and status='queued', then transitions through running to a terminal state; result payload is stored in audit_runs.report and audit_runs.summary.
- runAuditMode must create/transition a session_modes row with mode_type='audit' to enabled, and may enqueue multiple audit_runs (accessibility/performance/seo/best_practices) for the same page_url; duplicate enqueues within a short window must be de-deduped by (session_id,audit_type,page_url) while status in ('queued','running').
- runDebuggerMode must create/transition a session_modes row with mode_type='debugger' to enabled; only one enabled debugger mode may exist per session.
- FK integrity: no logs, artifacts, audit runs, or mode entries may exist for a non-existent session; deleting a session cascades to dependent rows.
- Quota enforcement: when inserting browser_logs, the system must enforce browser_sessions.log_buffer_bytes <= log_buffer_limit_bytes by either rejecting inserts or evicting oldest logs for that session before insert; eviction must preserve referential integrity and keep newest logs.
- Session expiration: if browser_sessions.last_seen_at is older than a configured TTL, status transitions from active to expired and tools must refuse to run mutating actions (wipeLogs, screenshot, audits, modes) on expired/closed sessions.