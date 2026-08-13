# XHS MCP Service — local MCP environment

This backend supports an MCP service that proxies access to Xiaohongshu (XHS) by maintaining an authenticated session (cookie) and recording fetch/search operations for notes, their content, and comments. It also persists posted comments and provides auditability, deduplication, and basic lifecycle/status tracking for upstream calls and user actions.

Repository: https://github.com/Sun9220/xhs-mcp
Homepage: https://smithery.ai/server/@Sun9220/xhs-mcp

## Datastore

- `sessions.json` — Represents the XHS authenticated context used by the service (cookie jar + validity) and its health. Used by check_cookie and as the credential source for all other tools. (12 rows; fields: ['id', 'status', 'cookie_raw', 'cookie_fingerprint', 'user_identifier', 'last_checked_at', 'last_ok_at', 'last_error_code', 'last_error_message', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'invalid', 'rotating', 'disabled']
  - constraint: at most one active session at a time: unique(status) where status='active'
  - constraint: unique(cookie_fingerprint) where cookie_fingerprint is not null
  - constraint: expires_at >= created_at where expires_at is not null
- `api_calls.json` — Append-only log of service tool invocations and upstream XHS requests. Drives observability, rate limiting, debugging, and provides a backing store for tools whose parameter schemas are empty (keywords/url/note_id/comment are extracted from runtime inputs). (18 rows; fields: ['id', 'session_id', 'tool_name', 'status', 'input', 'upstream_method', 'upstream_url', 'upstream_status_code', 'duration_ms', 'error_code', 'error_message', 'response_summary', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'throttled']
  - constraint: duration_ms >= 0 where duration_ms is not null
  - constraint: upstream_status_code between 100 and 599 where upstream_status_code is not null
  - constraint: tool_name in ('check_cookie','home_feed','search_notes','get_note_content','get_note_comments','post_comment')
  - constraint: input must include {keywords} when tool_name='search_notes'
- `notes.json` — Canonical store of XHS notes encountered via home_feed, search_notes, and get_note_content. Stores identifiers, URLs, xsec tokens when present, and normalized content metadata. (17 rows; fields: ['id', 'xhs_note_id', 'status', 'canonical_url', 'url_with_xsec_token', 'xsec_token', 'title', 'body_text', 'author_xhs_id', 'author_name', 'cover_image_url', 'media_urls', 'like_count', 'comment_count', 'collected_from', 'last_content_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['discovered', 'content_fetched', 'deleted', 'unavailable']
  - constraint: unique(xhs_note_id)
  - constraint: like_count >= 0 where like_count is not null
  - constraint: comment_count >= 0 where comment_count is not null
- `comments.json` — Stores comments fetched from get_note_comments and comments created via post_comment. Supports threading via parent_comment_id when available. (18 rows; fields: ['id', 'note_id', 'xhs_comment_id', 'parent_comment_id', 'status', 'author_xhs_id', 'author_name', 'content', 'like_count', 'posted_via_call_id', 'fetched_via_call_id', 'upstream_created_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fetched', 'pending_post', 'posted', 'post_failed', 'deleted']
  - constraint: like_count >= 0 where like_count is not null
  - constraint: unique(note_id, xhs_comment_id) where xhs_comment_id is not null
  - constraint: content length between 1 and 1000
- `search_queries.json` — Tracks search_notes usage: keyword searches and their result associations for caching, throttling, and replay/debug. Even though the tool schema is empty, runtime input is stored here. (18 rows; fields: ['id', 'session_id', 'api_call_id', 'status', 'keywords', 'normalized_keywords', 'result_note_ids', 'result_count', 'cached_until', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: keywords length between 1 and 200
  - constraint: normalized_keywords = lower(trim(keywords))
  - constraint: result_count >= 0 where result_count is not null
  - constraint: if cached_until is not null then cached_until > created_at

## Business rules enforced by the tools

- check_cookie must select the single sessions row where status='active'; it updates last_checked_at on every run and sets status to 'active' on success, otherwise to 'expired' or 'invalid' depending on upstream response classification.
- home_feed must create an api_calls row with tool_name='home_feed' and status transitions received->running->(succeeded|failed); any notes discovered must be upserted into notes by unique(xhs_note_id) and set status at least 'discovered'.
- search_notes must persist keywords into search_queries (normalized_keywords required). If a non-expired cached search exists (cached_until > now), the service may return cached results without an upstream call but must still create an api_calls row marked succeeded with response_summary.source='cache'.
- get_note_content requires an input.url that includes xsec_token; the service must parse and store xsec_token and url_with_xsec_token in notes (upsert by xhs_note_id when derivable, else create a note with discovered status and fill urls). On successful fetch it must set notes.status='content_fetched' and last_content_fetched_at=now.
- get_note_comments requires an input.url that includes xsec_token; fetched comments must be upserted by unique(note_id, xhs_comment_id) where xhs_comment_id is present. Deleted/unavailable upstream states must transition notes.status to 'unavailable' or 'deleted'.
- post_comment must require non-empty comment content (1..1000 chars) and a resolvable target note (notes.xhs_note_id matches input.note_id). It must create a comments row with status='pending_post' before calling upstream, then transition to 'posted' and fill xhs_comment_id on success, otherwise transition to 'post_failed' and persist error details on the linked api_calls row.
- All tools must be blocked (api_calls status='failed' with error_code='NO_ACTIVE_SESSION') if no sessions row has status='active', except check_cookie which is allowed to run and update session status.
- FK integrity: comments.note_id must reference notes.id; deleting a note is not allowed while comments exist unless comments are first soft-deleted (status='deleted').
- Rate limiting/throttling: if too many api_calls are running or recent failures exceed a threshold, new calls may be recorded as api_calls.status='throttled' without upstream access.