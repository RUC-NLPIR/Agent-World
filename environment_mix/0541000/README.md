# Bright Data — local MCP environment

This backend powers Bright Data-style web acquisition workflows: SERP fetching, single-URL scraping (markdown/html) and AI-assisted structured extraction, plus a stateful remote "scraping browser" session with navigations and actions. It stores each tool invocation as a request with parameters and status, persists durable results (including cached web-data lookups), and tracks session-level usage statistics and quotas.

Repository: https://github.com/brightdata/brightdata-mcp
Homepage: https://smithery.ai/server/@luminati-io/brightdata-mcp

## Datastore

- `projects.json` — Tenant boundary for API usage. A project owns API keys, requests, browser sessions, and usage counters. (18 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_request_quota', 'monthly_byte_quota', 'monthly_browser_action_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name) WHERE status != 'deleted'
  - constraint: monthly_request_quota >= 0
  - constraint: monthly_byte_quota >= 0
  - constraint: monthly_browser_action_quota >= 0
- `api_keys.json` — API credentials used to authenticate tool calls. Keys belong to a project and can be rotated/revoked. (18 rows; fields: ['id', 'project_id', 'key_prefix', 'key_hash', 'name', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(project_id, key_prefix)
  - constraint: unique(key_hash)
  - constraint: foreign key(project_id) references projects(id) on delete restrict
- `tool_requests.json` — Durable log of every tool call (search, scrape, extract, web_data*). Stores validated parameters, status, and high-level response metadata. (18 rows; fields: ['id', 'project_id', 'api_key_id', 'session_id', 'tool_name', 'status', 'engine', 'query', 'cursor', 'url', 'keyword', 'pages_to_search', 'extraction_prompt', 'first_name', 'last_name', 'num_of_reviews', 'days_limit', 'num_of_comments', 'response_content_type', 'response_bytes', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(project_id) references projects(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: tool_name = 'search_engine' => query is not null
  - constraint: tool_name = 'search_engine' => engine in ('google','bing','yandex') and engine is not null
- `tool_results.json` — Stores outputs for tool_requests. Supports multiple result items for SERP and multi-record web-data responses, as well as single payloads for scrapes/extract. (18 rows; fields: ['id', 'request_id', 'result_kind', 'sequence', 'source_url', 'title', 'description', 'payload_text', 'payload_json', 'next_cursor', 'cache_hit', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `result_kind`: ['serp_item', 'document_markdown', 'document_html', 'extracted_json', 'web_data_json', 'session_stats_json']
  - constraint: foreign key(request_id) references tool_requests(id) on delete cascade
  - constraint: unique(request_id, result_kind, sequence)
  - constraint: sequence >= 0
  - constraint: cache_hit in (true,false)
- `browser_sessions.json` — Stateful scraping browser sessions used by the scraping_browser_* tools. Stores current page, history pointers, and counts. (18 rows; fields: ['id', 'project_id', 'api_key_id', 'session_id', 'status', 'current_url', 'current_title', 'history', 'history_index', 'action_count', 'last_activity_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closed', 'expired']
  - constraint: foreign key(project_id) references projects(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: history_index >= 0
  - constraint: action_count >= 0
- `browser_actions.json` — Append-only log of scraping_browser_* tool calls executed within a browser_session. Used for debugging, replay, and usage metering. (20 rows; fields: ['id', 'browser_session_id', 'project_id', 'api_key_id', 'action_type', 'url', 'selector', 'text', 'submit', 'timeout_ms', 'full_page', 'status', 'result_ref', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign key(browser_session_id) references browser_sessions(id) on delete cascade
  - constraint: foreign key(project_id) references projects(id) on delete restrict
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: action_type = 'scraping_browser_navigate' => url is not null

## Business rules enforced by the tools

- Authentication: every tool invocation must be associated with an active api_keys record (status='active') and its project must be active (projects.status='active'); otherwise the request is rejected and no tool_requests row is created.
- Quota enforcement: before creating a tool_requests row in status='queued', the service must verify that the project has not exceeded monthly_request_quota and monthly_byte_quota; for scraping browser actions it must also verify monthly_browser_action_quota. Exceeding quota yields a failed request with error_code='quota_exceeded'.
- Tool parameter validation: tool_requests.tool_name determines which parameter fields are required; the database constraints listed (e.g., search_engine requires query and engine) must be upheld by the application and enforced by check constraints.
- Cursor continuity: for tool_name='search_engine', if cursor is provided it must have been previously issued as tool_results.next_cursor for the same project_id and same query+engine within a configurable TTL window (e.g., 24h); otherwise reject as invalid cursor.
- Result write-once: tool_results rows are immutable after creation except updated_at; correcting a response requires creating a new tool_requests record (auditability).
- Request completion semantics: when tool_requests.status transitions to 'succeeded', at least one tool_results row must exist for that request_id; when status transitions to 'failed', error_code and error_message must be set.
- Cache semantics for web_data_*: when a web_data_* tool returns from cache, tool_results.cache_hit must be true and expires_at must be non-null; when not from cache, cache_hit may be false and expires_at may be null.
- Browser session validity: a browser_sessions record must be status='active' and last_activity_at <= now() <= expires_at to accept any new browser_actions; otherwise actions are rejected and the session is marked expired.
- Browser history: scraping_browser_go_back and scraping_browser_go_forward must not move history_index out of bounds of history; attempts should fail with a clear error and must not change current_url.
- Session stats: session_stats tool aggregates over tool_requests where session_id matches the current session and created_at is within the session lifetime, returning a session_stats_json result_kind containing counts by tool_name, total_response_bytes, total_failures, and total_browser_actions.