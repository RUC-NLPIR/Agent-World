# DeepResearch — local MCP environment

DeepResearch stores multi-step web research sessions initiated from a natural-language query. A session runs iterative research steps (e.g., searching, reading, extracting notes/citations) until a target depth is reached, then compiles a final report and marks the session complete.

Repository: https://github.com/ameeralns/DeepResearchMCP
Homepage: https://smithery.ai/server/@ameeralns/DeepResearchMCP

## Datastore

- `research_sessions.json` — Top-level research run created from an input query and a requested depth. Tracks lifecycle, progress, and finalization. (18 rows; fields: ['id', 'query', 'requested_depth', 'current_depth', 'max_steps', 'steps_executed', 'status', 'last_error', 'timeout_ms_default_report', 'timeout_ms_default_complete', 'final_report_id', 'created_at', 'updated_at', 'completed_at'])
  - lifecycle `status`: ['initialized', 'running', 'awaiting_report', 'reporting', 'completed', 'failed', 'cancelled']
  - constraint: required(query)
  - constraint: requested_depth >= 1 and requested_depth <= 10
  - constraint: current_depth >= 0 and current_depth <= requested_depth
  - constraint: max_steps >= 1 and max_steps <= 1000
- `research_steps.json` — One incremental step of a research session (e.g., generate subqueries, search, read sources, extract notes). execute-research-step appends and completes exactly one next pending step per call. (18 rows; fields: ['id', 'session_id', 'step_index', 'depth', 'kind', 'status', 'input', 'output', 'error', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'running', 'succeeded', 'failed', 'skipped']
  - constraint: fk(session_id) references research_sessions(id) on delete cascade
  - constraint: unique(session_id, step_index)
  - constraint: depth >= 1 and depth <= 10
  - constraint: step_index >= 1
- `sources.json` — Web sources discovered and/or fetched during research. Normalizes URL-level metadata and content snapshots for citation and extraction. (18 rows; fields: ['id', 'session_id', 'discovered_in_step_id', 'url', 'title', 'publisher', 'published_at', 'retrieval_status', 'http_status', 'content_text', 'content_sha256', 'relevance_score', 'created_at', 'updated_at'])
  - lifecycle `retrieval_status`: ['discovered', 'fetched', 'fetch_failed']
  - constraint: fk(session_id) references research_sessions(id) on delete cascade
  - constraint: fk(discovered_in_step_id) references research_steps(id) on delete set null
  - constraint: unique(session_id, url)
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
- `research_reports.json` — Generated report artifacts for a research session. generate-report creates a new report version and attaches it to the session. (19 rows; fields: ['id', 'session_id', 'version', 'status', 'timeout_ms', 'report_markdown', 'summary', 'citations', 'error', 'created_at', 'updated_at', 'generated_at'])
  - lifecycle `status`: ['generating', 'ready', 'failed']
  - constraint: fk(session_id) references research_sessions(id) on delete cascade
  - constraint: unique(session_id, version)
  - constraint: timeout_ms >= 1000 and timeout_ms <= 600000
  - constraint: citations is array (default [])

## Business rules enforced by the tools

- initialize-research(query, depth) creates a research_sessions row with status='initialized', requested_depth=depth (default 3), current_depth=0, steps_executed=0, and creates an initial research_steps row (kind='plan', status='pending', step_index=1, depth=1). It returns sessionId=research_sessions.id.
- execute-research-step(sessionId) must fail if research_sessions.status in ('completed','failed','cancelled'). Otherwise it selects the smallest step_index with status='pending' for that session, marks it running, produces output, then marks it succeeded/failed. If no pending steps remain and current_depth >= requested_depth, session.status transitions to 'awaiting_report'.
- execute-research-step must increment research_sessions.steps_executed exactly once per executed step and must not exceed research_sessions.max_steps; exceeding max_steps transitions the session to status='failed' with last_error='max_steps_exceeded'.
- During step execution, discovered URLs are upserted into sources by unique(session_id,url). A source may transition retrieval_status from discovered->fetched or discovered->fetch_failed only.
- generate-report(sessionId, timeout) creates a new research_reports row with status='generating' and version=(max(version)+1) per session. While generating, the session status transitions to 'reporting' (from awaiting_report or running). On success it sets report_markdown, citations, status='ready', generated_at, and sets research_sessions.final_report_id to this report id.
- generate-report must enforce timeout_ms within [1000,600000]; if the caller omits timeout, it uses research_sessions.timeout_ms_default_report (default 60000).
- complete-research(query, depth, timeout) is equivalent to: initialize-research(query, depth) then repeatedly execute-research-step(sessionId) until session.status='awaiting_report' or a terminal status is reached, then call generate-report(sessionId, timeout) and finally transition session to 'completed' if report.status='ready'. Total wall-clock time must not exceed timeout (default 180000) or the session is marked failed with last_error='complete_timeout'.
- A session can only transition to 'completed' if it has a non-null final_report_id referencing a research_reports row with status='ready'.
- FK integrity must be enforced: deleting a session cascades delete to steps, sources, and reports; deleting a step sets sources.discovered_in_step_id to null; deleting a report sets research_sessions.final_report_id to null.