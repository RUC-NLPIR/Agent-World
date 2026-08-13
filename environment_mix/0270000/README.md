# Web3 Research — local MCP environment

This backend stores token-centric research workspaces, their research plans (broken into sections), and the supporting evidence gathered from web searches and fetched URLs. Primary workflows are: create a plan for a token, run searches by keyword/source, fetch and cache source content, attach findings to plan sections, and track section completion status.

Repository: https://github.com/aaronjmars/web3-research-mcp
Homepage: https://smithery.ai/server/@aaronjmars/web3-research-mcp

## Datastore

- `tokens.json` — Canonical crypto/Web3 token or project identity used to scope research and searches. (31 rows; fields: ['id', 'name', 'ticker', 'slug', 'status', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(slug)
  - constraint: length(ticker) between 1 and 16
  - constraint: ticker must match regex ^[A-Z0-9]+$ after normalization
- `research_plans.json` — A structured research plan for a given token, including the plan content and an overall lifecycle. Created by create-research-plan and used by subsequent research tools. (37 rows; fields: ['id', 'token_id', 'title', 'plan', 'status', 'active_plan_version', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'completed', 'archived']
  - constraint: foreign key (token_id) references tokens(id) on delete restrict
  - constraint: unique(token_id, status) where status in ('draft','active') (at most one draft/active plan per token)
  - constraint: active_plan_version >= 1
- `plan_sections.json` — Per-plan section tracker updated via update-status (e.g., projectInfo, technicalFundamentals). Also serves as an anchor to attach findings/evidence to a section. (35 rows; fields: ['id', 'plan_id', 'section_key', 'display_name', 'status', 'notes', 'sort_order', 'created_at', 'updated_at'])
  - lifecycle `status`: ['planned', 'in_progress', 'completed']
  - constraint: foreign key (plan_id) references research_plans(id) on delete cascade
  - constraint: unique(plan_id, section_key)
  - constraint: sort_order >= 0
  - constraint: length(section_key) between 1 and 64
- `search_queries.json` — Audit and caching layer for calls to the search tool and higher-level research tools that issue searches (research-with-keywords, search-source, research-source, research-token). Stores query text, search type, and how it was initiated. (40 rows; fields: ['id', 'token_id', 'plan_id', 'initiator_tool', 'query', 'search_type', 'source', 'keywords', 'status', 'provider', 'result_count', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign key (token_id) references tokens(id) on delete set null
  - constraint: foreign key (plan_id) references research_plans(id) on delete set null
  - constraint: result_count >= 0
  - constraint: length(query) between 1 and 2048
- `resources.json` — Discovered and/or fetched resources (URLs and resource:// internal references). Powers list-resources and fetch-content caching, and stores content snapshots. (39 rows; fields: ['id', 'search_query_id', 'token_id', 'plan_id', 'plan_section_id', 'source', 'url', 'url_hash', 'title', 'content_format', 'content', 'content_json', 'http_status', 'fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['discovered', 'fetch_queued', 'fetched', 'fetch_failed', 'archived']
  - constraint: unique(url_hash)
  - constraint: foreign key (search_query_id) references search_queries(id) on delete set null
  - constraint: foreign key (token_id) references tokens(id) on delete set null
  - constraint: foreign key (plan_id) references research_plans(id) on delete set null

## Business rules enforced by the tools

- create-research-plan must upsert tokens by slug (lower(tokenName)+':'+lower(tokenTicker)) and ensure ticker is uppercased before storing.
- create-research-plan must create exactly one research_plans row in status='active' for the token if none exists; if an active plan exists, it must either reuse it or archive it before creating a new active plan (never two active plans per token).
- create-research-plan must create plan_sections rows for every section in the generated plan; each section_key must be unique per plan.
- update-status must update exactly one plan_sections row identified by (plan_id context, section_key=section). If no active plan exists for the current token/work context, the call must fail.
- update-status may only set status to planned|in_progress|completed and must obey the declared transitions; invalid transitions must be rejected.
- search must create a search_queries row with initiator_tool='search', store query and search_type, and transition status queued->running->(succeeded|failed).
- research-with-keywords must record keywords[] on search_queries and generate one or more search_queries rows whose query field includes tokenName/tokenTicker and the keyword; each resulting resource URL must be deduplicated via resources.url_hash.
- search-source/research-source/research-token must store the provided source string on search_queries.source and on any created resources.source.
- fetch-content must canonicalize the input url and resolve resource:// identifiers to a resources row; it must update resources.content_format/content and set status to fetched or fetch_failed accordingly.
- list-resources must return resources rows; results should be ordered by updated_at desc and exclude archived by default (unless explicitly requested by the server implementation).
- For any resources row linked to plan_section_id, the referenced plan_sections.plan_id must equal resources.plan_id (enforce via application-level integrity check on write).
- Caching rule: fetch-content should not refetch a resources row in status='fetched' with fetched_at within a configured TTL (e.g., 24h) unless forced by the server implementation; if refetched, status must move fetched->fetch_queued->fetched.
- Result limits: a single search_queries execution must not persist more than a configured maximum number of resources (e.g., 100) and must set result_count accordingly.
- Data retention: search_queries and resources may be archived, but foreign keys must remain valid; deletions must be restricted or implemented as soft-delete via status='archived'.