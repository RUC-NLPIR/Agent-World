# Automated UI Debuger and Tester — local MCP environment

This backend stores execution sessions for automated UI debugging and testing, including page analyses, navigation/workflow runs, API endpoint test suites, and crawl jobs. It persists artifacts like screenshots, DOM snapshots, console logs, performance metrics, and per-step results so read-oriented tools can retrieve accumulated context while mutating tools append new events and outputs to the active session.

Repository: https://github.com/samihalawa/visual-ui-debug-agent-mcp
Homepage: https://smithery.ai/server/@samihalawa/visual-ui-debug-agent-mcp

## Datastore

- `sessions.json` — Top-level execution context for a user/tool run. All tool invocations and artifacts are scoped to a session to support stateful Playwright interactions (navigate/click/fill/etc.) and accumulated logs/artifacts retrieval. (18 rows; fields: ['id', 'status', 'origin_tool', 'start_url', 'current_url', 'device', 'default_wait_until', 'default_timeout_ms', 'console_capture_enabled', 'element_mapping_enabled', 'stability_wait_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closing', 'closed', 'errored']
  - constraint: console_capture_enabled IN (true,false)
  - constraint: element_mapping_enabled IN (true,false)
  - constraint: stability_wait_ms >= 0
  - constraint: default_timeout_ms IS NULL OR default_timeout_ms BETWEEN 1 AND 300000
- `jobs.json` — Durable records of tool invocations that produce structured outputs and/or multiple artifacts: page analysis, API endpoint testing, navigation/workflow validation, performance runs, visual comparisons, screenshots, DOM inspections, tunnel actions, memory actions, and sitemap crawling. (19 rows; fields: ['id', 'session_id', 'tool_name', 'status', 'input', 'normalized_target_url', 'started_at', 'finished_at', 'error_message', 'output_format', 'summary', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: tool_name IS NOT NULL
  - constraint: normalized_target_url IS NULL OR normalized_target_url LIKE 'http%'
  - constraint: output_format IS NULL OR output_format IN ('json','markdown','text')
  - constraint: finished_at IS NULL OR started_at IS NOT NULL
- `job_steps.json` — Ordered step execution for navigation_flow_validator and ui_workflow_validator. Stores requested step definition plus execution outcome, timing, and optional captured artifacts per step. (17 rows; fields: ['id', 'job_id', 'step_index', 'description', 'action', 'selector', 'value', 'url', 'script', 'is_optional', 'status', 'started_at', 'finished_at', 'error_message', 'screenshot_artifact_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'running', 'passed', 'failed', 'skipped']
  - constraint: unique(job_id, step_index)
  - constraint: step_index >= 0
  - constraint: is_optional IN (true,false)
  - constraint: url IS NULL OR url LIKE 'http%'
- `artifacts.json` — Binary/large outputs and structured captures produced by jobs or sessions: screenshots, diff images, DOM snapshots, visible text/html dumps, element maps, performance reports, sitemap outputs, and console log export batches. (18 rows; fields: ['id', 'session_id', 'job_id', 'kind', 'name', 'source_url', 'selector', 'full_page', 'mime_type', 'byte_size', 'storage_uri', 'content', 'created_at', 'updated_at'])
  - lifecycle `kind`: ['screenshot', 'screenshot_grid', 'visual_diff', 'dom_snapshot', 'visible_text', 'visible_html', 'element_map', 'performance_report', 'sitemap', 'api_test_report', 'console_export']
  - constraint: byte_size IS NULL OR byte_size >= 0
  - constraint: full_page IS NULL OR full_page IN (true,false)
  - constraint: name IS NULL OR length(name) BETWEEN 1 AND 200
  - constraint: storage_uri IS NULL OR length(storage_uri) <= 2048
- `event_logs.json` — Append-only event stream for console logs, network/test traces, tunnel actions, and debug memory operations. Used to implement playwright_console_logs (retrieve/clear/limit/type filtering) and to persist debug_memory and tunnel_helper state changes. (18 rows; fields: ['id', 'session_id', 'job_id', 'event_type', 'severity', 'message', 'data', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['console', 'api_endpoint_result', 'tunnel', 'memory', 'crawler', 'playwright_action']
  - constraint: occurred_at <= created_at + interval '5 minutes' OR occurred_at IS NOT NULL
  - constraint: severity IS NULL OR severity IN ('log','info','warning','error','debug')
  - constraint: event_type IN ('console','api_endpoint_result','tunnel','memory','crawler','playwright_action')

## Business rules enforced by the tools

- Every job.input must validate against the corresponding tool JSON-Schema; the backend stores it verbatim in jobs.input and may additionally set jobs.normalized_target_url for URL-bearing tools.
- Jobs must follow lifecycle transitions: queued -> running -> (succeeded|failed|cancelled); cancelled jobs must not create new job_steps or artifacts after cancellation time.
- For navigation_flow_validator and ui_workflow_validator, jobs must create job_steps rows with contiguous step_index starting at 0 and unique(job_id, step_index).
- ui_workflow_validator.steps[].action and navigation_flow_validator.steps[].action must be one of the allowed enums; required per-action fields must be present (e.g., fill/select require selector and value; navigate requires url; evaluate requires script; click/hover require selector; verifyUrl requires url or value as configured by implementation).
- playwright_console_logs reads from event_logs where event_type='console' and session_id matches the active session; 'type' filtering maps to severity (type='all' returns all severities). 'limit' caps returned rows; if clear=true, returned rows are deleted or marked redacted for that session after retrieval.
- console_monitor creates event_logs rows with event_type='console' for the specified duration; filterTypes restrict which severities are persisted/returned for that job execution.
- playwright_screenshot must create an artifacts row with kind='screenshot' and name unique per session (unique(session_id, name)) to ensure deterministic retrieval by URI name.
- visual_comparison must enforce threshold in range [0.0, 1.0] and must create artifacts for at least the two source screenshots plus an optional visual_diff artifact when differences exceed threshold.
- batch_screenshot_urls and screenshot_local_files must enforce gridSize as an integer between 1 and 10; produced output should be stored as kind='screenshot_grid' artifact and individual screenshots as kind='screenshot'.
- performance_analysis must enforce iterations as an integer between 1 and 20 and create a kind='performance_report' artifact per iteration (or a single aggregated artifact) linked to the job.
- dom_inspector must create a kind='dom_snapshot' artifact that includes selector, includeChildren/includeStyles reflected in artifacts.content metadata and/or jobs.input.
- tunnel_helper action='store' must include tunnelUrl and writes an event_logs row with event_type='tunnel' and data {localPort, tunnelUrl}; action='retrieve' returns the most recent stored tunnelUrl for that localPort (optionally scoped by session).
- debug_memory action='save' must include key and value; it writes an event_logs row with event_type='memory' and data {action:'save', key, category, value}. action='retrieve' returns the latest saved value for the key (and optional category). action='list' returns distinct keys filtered by category when provided. action='clear' deletes or redacts memory events in scope.
- sitemap_crawler must enforce maxDepth as an integer between 1 and 10; sameDomainOnly and includeText default to true; it must store final output as a kind='sitemap' artifact with mime_type consistent with outputFormat.