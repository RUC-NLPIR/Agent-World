# Octagon MCP Server — local MCP environment

This backend powers the Octagon MCP Server by brokering requests to a set of specialized intelligence agents (public markets, private markets, web scraping, and security) and storing conversational sessions plus the resulting research artifacts. The main workflow is: a client invokes an agent tool -> the server creates an agent run within a session -> the run produces one or more output artifacts (structured extracts, transcript snippets, financial tables, citations) that are stored and can be audited/queried later.

Repository: https://github.com/OctagonAI/octagon-mcp-server
Homepage: https://smithery.ai/server/@OctagonAI/octagon-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace container for agent usage, quota enforcement, and audit boundaries. In a real Octagon deployment this would map to an organization/project that owns sessions, runs, and stored artifacts. (18 rows; fields: ['id', 'name', 'slug', 'plan', 'status', 'monthly_run_quota', 'monthly_artifact_quota', 'monthly_scrape_url_quota', 'retention_days', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: monthly_run_quota >= 0
  - constraint: monthly_artifact_quota >= 0
  - constraint: monthly_scrape_url_quota >= 0
- `api_keys.json` — API credentials used by MCP clients to call Octagon agent tools; scoped to a workspace for quota and audit attribution. (19 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'scopes', 'status', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: unique(workspace_id, key_prefix)
  - constraint: key_hash length >= 32
  - constraint: scopes is non-empty array
  - constraint: expires_at is null or expires_at > created_at
- `agent_tools.json` — Catalog of available Octagon MCP tools/agents. This table is the authoritative mapping for the 11 tool names in the surface and is used for authorization, routing, and analytics. (18 rows; fields: ['id', 'tool_name', 'category', 'market_scope', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['enabled', 'disabled', 'deprecated']
  - constraint: unique(tool_name)
  - constraint: tool_name in ('octagon-sec-agent','octagon-transcripts-agent','octagon-financials-agent','octagon-stock-data-agent','octagon-companies-agent','octagon-funding-agent','octagon-deals-agent','octagon-investors-agent','octagon-scraper-agent','octagon-deep-research-agent','octagon-debts-agent')
- `sessions.json` — Conversation/research sessions that group multiple tool invocations (agent runs) into a single analytical thread for a workspace. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'title', 'status', 'context', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'archived', 'deleted']
  - constraint: title is null or length(title) <= 200
  - constraint: api_key_id is null or api_keys.workspace_id = sessions.workspace_id
- `agent_runs.json` — An execution record for invoking one of the 11 Octagon agents. Even though the MCP tool parameters are empty schemas, the real request prompt/messages are stored here for reproducibility, audit, and troubleshooting. (20 rows; fields: ['id', 'workspace_id', 'session_id', 'api_key_id', 'tool_id', 'input', 'status', 'error_code', 'error_message', 'started_at', 'finished_at', 'duration_ms', 'usage', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: sessions.workspace_id = agent_runs.workspace_id
  - constraint: api_key_id is null or api_keys.workspace_id = agent_runs.workspace_id
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: finished_at is null or started_at is not null
- `artifacts.json` — Persisted outputs produced by agent runs: transcript extracts, financial tables, scraped structured data, deal/funding/investor records, citations, and synthesized research reports. (20 rows; fields: ['id', 'workspace_id', 'session_id', 'run_id', 'tool_id', 'artifact_type', 'title', 'content', 'source_urls', 'content_hash', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: sessions.workspace_id = artifacts.workspace_id
  - constraint: agent_runs.workspace_id = artifacts.workspace_id
  - constraint: agent_runs.session_id = artifacts.session_id
  - constraint: artifacts.tool_id = agent_runs.tool_id

## Business rules enforced by the tools

- Each of the 11 MCP tools must map to exactly one row in agent_tools with agent_tools.tool_name equal to the tool surface name; invocations of unknown tool_name are rejected.
- An API key can invoke an agent tool only if api_keys.status='active', (api_keys.expires_at is null or now < expires_at), and the tool_name is included in api_keys.scopes (or scopes contains a wildcard such as '*').
- A tool invocation creates exactly one agent_runs row; status starts at 'queued' and may only transition according to agent_runs.lifecycle.transitions.
- agent_runs for a session are only allowed when sessions.status='open'. If sessions.status is 'archived' or 'deleted', new runs must be rejected.
- workspace quotas must be enforced at run creation time: if the count of agent_runs.created_at in the current calendar month for the workspace is >= workspaces.monthly_run_quota, the run must be rejected with error_code='quota_exceeded'.
- For octagon-scraper-agent, the number of distinct URLs appearing in artifacts.source_urls (or in agent_runs.input.url(s)) in the current month must not exceed workspaces.monthly_scrape_url_quota; otherwise reject with error_code='quota_exceeded'.
- Artifacts may only be created for agent_runs with status 'running' or 'succeeded'; once a run is 'failed' or 'cancelled', artifact creation must be rejected (except artifact_type='raw_response' for debugging if workspace.plan='enterprise').
- An artifact must have workspace_id/session_id/run_id all consistent via foreign keys: artifacts.session_id must equal agent_runs.session_id and both must belong to the same workspace.
- When a new artifact is marked as the latest version for the same logical output (same artifact_type and same content_hash scope), older artifacts in that session should transition to status='superseded' (never back to 'active').
- Workspace status enforcement: if workspaces.status != 'active', all tool invocations must be rejected; if status='deleted', read access to sessions/runs/artifacts must return not found.
- Retention enforcement: artifacts and sessions older than workspaces.retention_days may be transitioned to status='deleted' by a scheduled job; deleted rows remain for audit but content may be redacted (content replaced with minimal tombstone).
- For security: agent_runs.input and artifacts.content must be validated to not store raw API keys/secrets; if detected, the system must redact and record error_code='secret_detected' or set artifact/status appropriately.