# Hyperbrowser — local MCP environment

Hyperbrowser stores persistent browser profiles plus execution records for web actions: single-page scrapes, multi-page crawls, structured extraction runs, web searches, and interactive browser-agent sessions. The main workflow is: a client selects/creates a profile, runs one of the tools (scrape/crawl/extract/search/agent), and the service records a job plus its artifacts (pages, results, extracted JSON, transcripts) for later inspection and billing/limits.

Repository: https://github.com/hyperbrowserai/mcp
Homepage: https://smithery.ai/server/@hyperbrowserai/mcp

## Datastore

- `profiles.json` — Persistent Hyperbrowser profiles representing a reusable cloud-browser identity (cookies/storage/preferences) that can be attached to scrapes, crawls, searches, and agent sessions. (18 rows; fields: ['profile_id', 'display_name', 'status', 'storage_bucket_key', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleting', 'deleted']
  - constraint: profile_id is unique
  - constraint: status != 'active' implies storage_bucket_key may be null but profile is not attachable to new jobs
  - constraint: updated_at >= created_at
- `jobs.json` — Canonical execution record for every tool invocation: scraping, crawling, extraction, search, and browser-agent sessions. Stores normalized inputs/outputs even when the public tool surface does not expose parameters. (21 rows; fields: ['job_id', 'tool_name', 'profile_id', 'status', 'input', 'output', 'error_code', 'error_message', 'started_at', 'finished_at', 'cost_usd', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: job_id is unique
  - constraint: cost_usd >= 0
  - constraint: finished_at is null or finished_at >= started_at
  - constraint: status in ('succeeded','failed','cancelled') implies finished_at is not null
- `web_pages.json` — Deduplicated representation of fetched webpages (HTML/text/metadata) produced by scrape and crawl jobs and reused by extraction/agent steps. (19 rows; fields: ['page_id', 'job_id', 'url', 'canonical_url', 'http_status', 'content_type', 'title', 'text_content', 'html_storage_key', 'screenshot_storage_key', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `http_status`: []
  - constraint: page_id is unique
  - constraint: url is required and length <= 4096
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: unique(job_id, url)
- `search_results.json` — Result items returned by the search_with_bing tool, normalized for ranking and later retrieval/analysis. (18 rows; fields: ['result_id', 'job_id', 'rank', 'title', 'url', 'snippet', 'provider', 'created_at', 'updated_at'])
  - lifecycle `provider`: ['bing']
  - constraint: result_id is unique
  - constraint: rank >= 1
  - constraint: unique(job_id, rank)
  - constraint: unique(job_id, url)
- `agent_sessions.json` — Interactive browser automation sessions produced by browser_use_agent, openai_computer_use_agent, and claude_computer_use_agent. Stores instructions, model/provider selection, and execution transcript pointers. (18 rows; fields: ['session_id', 'job_id', 'agent_type', 'instructions', 'transcript_storage_key', 'final_url', 'created_at', 'updated_at'])
  - lifecycle `agent_type`: ['browser_use', 'openai_computer_use', 'claude_computer_use']
  - constraint: session_id is unique
  - constraint: unique(job_id)
  - constraint: job.tool_name in ('browser_use_agent','openai_computer_use_agent','claude_computer_use_agent') for rows in this table

## Business rules enforced by the tools

- Every tool invocation MUST create exactly one jobs row with tool_name matching the tool called, even if the public parameters schema is empty; any inferred/implicit inputs MUST be stored in jobs.input.
- create_profile MUST create one profiles row (status='active') and one jobs row (tool_name='create_profile', status='succeeded') whose output contains the created profile_id.
- delete_profile MUST transition profiles.status from 'active' -> 'deleting' -> 'deleted'; once status!='active' the profile MUST NOT be attachable to new jobs.
- list_profiles MUST return only profiles where status in ('active','deleting') by default; 'deleted' profiles are excluded from normal listing.
- scrape_webpage MUST create at least one web_pages row for the target URL when jobs.status='succeeded'; failures may still create a web_pages row with http_status set accordingly.
- crawl_webpages MUST create one web_pages row per successfully fetched URL; the system MUST enforce unique(job_id,url) to prevent duplicates during crawling.
- extract_structured_data MUST reference source content either by url in jobs.input or by a page_id embedded in jobs.input; on success, jobs.output MUST contain extracted JSON compatible with the requested schema stored in jobs.input.schema when present.
- search_with_bing MUST create one jobs row and N search_results rows; ranks MUST be contiguous starting at 1 for a given job_id.
- browser_use_agent/openai_computer_use_agent/claude_computer_use_agent MUST create one agent_sessions row linked to the job; transcript_storage_key MUST be set when the job succeeds.
- For any job: status transitions MUST follow jobs.lifecycle.transitions; once a job reaches a terminal state (succeeded/failed/cancelled) it MUST NOT transition again.
- FK integrity MUST be enforced: jobs.profile_id references profiles.profile_id; web_pages.job_id references jobs.job_id; search_results.job_id references jobs.job_id; agent_sessions.job_id references jobs.job_id.
- cost_usd MUST be computed and stored for every job; it MUST be >= 0 and MAY be 0 for administrative operations (create_profile/delete_profile/list_profiles).