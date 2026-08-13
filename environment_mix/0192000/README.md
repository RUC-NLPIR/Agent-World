# ScrapeGraph MCP Server — local MCP environment

This backend stores AI-assisted scraping and search runs initiated via the MCP tools, along with inputs, outputs, referenced URLs, and operational metadata. Main workflows: create a run for markdownify/smartscraper/searchscraper, optionally discover/search URLs, fetch and transform pages to markdown, and store structured extraction results with provenance and run status.

Repository: https://github.com/ScrapeGraphAI/scrapegraph-mcp
Homepage: https://smithery.ai/server/@ScrapeGraphAI/scrapegraph-mcp

## Datastore

- `projects.json` — Logical tenant/workspace boundary for runs, quotas, and configuration. In a real deployment this maps to an MCP server instance namespace or user workspace. (12 rows; fields: ['id', 'name', 'status', 'daily_run_quota', 'daily_page_fetch_quota', 'max_concurrent_runs', 'default_user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: daily_run_quota >= 0
  - constraint: daily_page_fetch_quota >= 0
  - constraint: max_concurrent_runs >= 1
- `api_keys.json` — Credentials used to authenticate calls into the MCP server and attribute usage to a project. (12 rows; fields: ['id', 'project_id', 'name', 'key_hash', 'prefix', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(project_id, name)
  - constraint: unique(prefix)
  - constraint: foreign key (project_id) references projects(id)
- `runs.json` — A single invocation of an MCP tool (markdownify, smartscraper, searchscraper) including prompts, target URL(s), and final output. (20 rows; fields: ['id', 'project_id', 'api_key_id', 'tool_name', 'user_prompt', 'website_url', 'input_options', 'status', 'error_code', 'error_message', 'output_payload', 'output_text', 'tokens_input', 'tokens_output', 'cost_usd', 'queued_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (project_id) references projects(id)
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: tool_name in ('markdownify','smartscraper','searchscraper')
  - constraint: ((tool_name = 'searchscraper') implies (user_prompt is not null and website_url is null))
- `web_resources.json` — Canonical registry of URLs seen by the system, used to de-duplicate fetches and attach metadata (content type, last fetch status). (18 rows; fields: ['id', 'canonical_url', 'raw_url', 'domain', 'content_type', 'robots_allowed', 'last_http_status', 'last_fetched_at', 'created_at', 'updated_at'])
  - constraint: unique(canonical_url)
  - constraint: last_http_status is null or (last_http_status >= 100 and last_http_status <= 599)
- `run_artifacts.json` — Per-run fetched pages, conversions to markdown, and structured extraction/search results with provenance and ordering. (18 rows; fields: ['id', 'run_id', 'web_resource_id', 'artifact_type', 'sequence', 'status', 'http_status', 'title', 'snippet', 'content_text', 'content_json', 'source_hash', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'ready', 'failed']
  - constraint: foreign key (run_id) references runs(id) on delete cascade
  - constraint: foreign key (web_resource_id) references web_resources(id)
  - constraint: sequence >= 0
  - constraint: unique(run_id, artifact_type, sequence)

## Business rules enforced by the tools

- Calling markdownify must create a runs row with tool_name='markdownify' and website_url set; the generated markdown is stored in runs.output_text and/or a run_artifacts row with artifact_type='markdown'.
- Calling smartscraper must create a runs row with tool_name='smartscraper', user_prompt set, and website_url set; the structured extraction result is stored in runs.output_payload and/or a run_artifacts row with artifact_type='extraction' (content_json).
- Calling searchscraper must create a runs row with tool_name='searchscraper' and user_prompt set; each returned result must be persisted as a run_artifacts row with artifact_type='search_result', increasing sequence reflecting rank, and web_resource_id pointing to a web_resources record for the result URL.
- A run cannot transition from succeeded/failed/cancelled back to queued/running; attempts must be rejected.
- For each project, the system must enforce daily_run_quota and daily_page_fetch_quota; if exceeded, new runs must be rejected or queued with status='cancelled' and error_code='quota_exceeded'.
- max_concurrent_runs must be enforced per project: if running runs >= max_concurrent_runs, new runs must remain queued until capacity frees or be rejected according to policy.
- web_resources.canonical_url must be normalized consistently (scheme/host casing, default ports removed, fragments stripped) and must be unique.
- When a page is fetched as part of any run, the system must upsert web_resources (canonical_url) and update last_http_status/last_fetched_at; the per-run fetch details must be recorded as run_artifacts with artifact_type='page_fetch'.
- api_keys presented by clients must be matched by prefix then verified by key_hash; only status='active' keys may create runs; revoked keys must be denied.
- Deleting a project (status='deleted') must prevent new runs and may optionally soft-delete or retain historical runs for audit; run_artifacts must remain FK-consistent.