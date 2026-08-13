# Browser Control — local MCP environment

This backend stores per-user browser sessions, the open tabs within those sessions, recent browsing history, and retrieved page content needed to support text extraction, link listing, and in-tab find/highlight. Main workflows: create/open/close/reorder tabs, list tabs, query recent history, fetch tab content in paged chunks via offset, and record find/highlight actions for auditing and rate-limiting.

Repository: https://github.com/eyalzh/browser-control-mcp
Homepage: https://smithery.ai/server/@eyalzh/browser-control-mcp

## Datastore

- `browser_sessions.json` — Represents a controllable browser instance/session for a user/device. Tools operate against the user's current active session. (12 rows; fields: ['id', 'user_id', 'device_id', 'browser_type', 'platform', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'revoked']
  - constraint: unique(user_id, device_id) where device_id is not null
  - constraint: created_at <= updated_at
- `browser_tabs.json` — Open/known tabs within a browser session. Maps directly to the numeric tab IDs used by the tools. (18 rows; fields: ['id', 'session_id', 'tab_id_numeric', 'url', 'title', 'status', 'is_active', 'window_id', 'pinned', 'index_in_window', 'opened_at', 'closed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'closing', 'closed']
  - constraint: unique(session_id, tab_id_numeric)
  - constraint: index_in_window >= 0
  - constraint: tab_id_numeric > 0
  - constraint: opened_at <= updated_at
- `browser_history_items.json` — Recent browsing history items per session/user, used to implement get-recent-browser-history with optional searchQuery filtering. (18 rows; fields: ['id', 'session_id', 'url', 'title', 'visit_count', 'last_visited_at', 'source', 'created_at', 'updated_at'])
  - constraint: unique(session_id, url)
  - constraint: visit_count >= 0
- `tab_content_snapshots.json` — Stores extracted full text and discovered links for a tab at a point in time to serve get-tab-web-content with offset paging and truncation behavior. (18 rows; fields: ['id', 'tab_record_id', 'content_version', 'url_at_capture', 'captured_at', 'status', 'text_content', 'text_length', 'links', 'mime_type', 'charset', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'stale', 'deleted']
  - constraint: unique(tab_record_id, content_version)
  - constraint: content_version >= 1
  - constraint: text_length >= 0
  - constraint: text_length = length(text_content)
- `tab_find_highlights.json` — Audit log of find/highlight operations executed in a tab, supporting rate-limiting, debugging, and UX analytics. (18 rows; fields: ['id', 'tab_record_id', 'query_phrase', 'status', 'match_count', 'error_message', 'requested_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['requested', 'applied', 'not_found', 'failed']
  - constraint: length(query_phrase) >= 1
  - constraint: match_count is null when status in ('requested','failed')
  - constraint: match_count >= 0 when match_count is not null

## Business rules enforced by the tools

- All tools operate in the context of exactly one active browser_sessions row for the authenticated user (status='active'); if none exists, the request fails.
- open-browser-tab(url): url must be a non-empty absolute URL with scheme in ('http','https'); create a browser_tabs row with status='open' and assign a unique tab_id_numeric within (session_id, tab_id_numeric).
- get-list-of-open-tabs: returns browser_tabs where session_id=<active session> and status='open', ordered by (window_id asc nulls last, index_in_window asc).
- close-browser-tabs(tabIds): every numeric tab id must exist as browser_tabs.tab_id_numeric in the active session with status='open'; set status to 'closing' then 'closed' with closed_at set; closing/closed tabs are not returned by get-list-of-open-tabs.
- reorder-browser-tabs(tabOrder): tabOrder must contain each currently open tab_id_numeric exactly once (no missing/extra/duplicates); update index_in_window for each open tab to match the new order (0..N-1) within its window (single-window implementations set window_id null for all).
- get-recent-browser-history(searchQuery): returns browser_history_items for the active session ordered by last_visited_at desc; if searchQuery is provided, it filters case-insensitively by substring match on url or title.
- get-tab-web-content(tabId, offset): tabId must refer to an open browser_tabs row in the active session; offset must be an integer >= 0; response is served from the latest tab_content_snapshots row for that tab (max(content_version) where status='ready'); if no ready snapshot exists or url has changed, a new snapshot is created and older ones transition to 'stale'.
- get-tab-web-content paging: offset is applied against tab_content_snapshots.text_content character index; if offset > text_length, return empty content and the same link list (or empty if snapshot missing).
- find-highlight-in-browser-tab(tabId, queryPhrase): tabId must refer to an open tab in the active session; queryPhrase length must be 1..5000; create a tab_find_highlights row with status='requested', then update to applied/not_found/failed after execution.
- FK integrity: browser_tabs.session_id must reference an existing browser_sessions.id; tab_content_snapshots.tab_record_id and tab_find_highlights.tab_record_id must reference existing browser_tabs.id; deleting a session is only allowed when status='revoked' and must cascade-delete or soft-delete dependent rows.
- Quota/limits: per session, a maximum of 200 open tabs is enforced; per tab, at most 20 content snapshots are retained (oldest 'stale' snapshots transition to 'deleted'); per tab, highlight requests are rate-limited to 30 per minute (enforced using tab_find_highlights.requested_at).