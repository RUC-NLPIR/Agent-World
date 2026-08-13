# Exa Websets Server — local MCP environment

This backend stores workspaces and API credentials, plus persistent "websets" that group harvested web content for later searching, enrichment, and notifications. The main workflow is: a workspace creates a webset, ingests/records web documents into it (often originating from Exa web search runs), runs searches over the webset, optionally applies AI enhancements to items, and configures notifications that trigger when new matching content appears.

Repository: https://github.com/waldzellai/exa-mcp-server-websets
Homepage: https://smithery.ai/server/@waldzellai/exa-mcp-server-websets

## Datastore

- `workspaces.json` — Tenant boundary for the Exa Websets Server. All websets, searches, enhancements, and notifications belong to a workspace. (12 rows; fields: ['id', 'name', 'plan', 'status', 'monthly_search_limit', 'monthly_enhancement_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_search_limit >= 0
  - constraint: monthly_enhancement_limit >= 0
- `api_keys.json` — API keys used by clients (including MCP server deployments) to authenticate and to associate actions with a workspace. May store Exa upstream credentials/aliases if needed for proxying. (11 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
- `websets.json` — A webset is a curated/managed collection of web content items for a workspace. Websets are the central unit for searching within a set, enhancing stored items, and attaching notifications. (12 rows; fields: ['id', 'workspace_id', 'name', 'description', 'source_config', 'status', 'item_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'archived', 'deleted']
  - constraint: unique(workspace_id, name)
  - constraint: item_count >= 0
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
- `webset_items.json` — Individual web documents/items stored in a webset, typically originating from Exa web search results or other sources. Items can be enhanced and searched. (18 rows; fields: ['id', 'webset_id', 'url', 'title', 'excerpt', 'content_text', 'source', 'exa_result_id', 'published_at', 'status', 'enhancements', 'enhanced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(webset_id, url)
  - constraint: fk(webset_id) references websets(id) on delete cascade
- `operations.json` — Unified log of user-facing operations executed by the MCP tools: Exa web searches, webset searches, enhancements, and notification checks. Enables auditing, status/progress, and quota enforcement. (21 rows; fields: ['id', 'workspace_id', 'api_key_id', 'type', 'webset_id', 'status', 'request', 'result', 'error', 'cost_units', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: fk(webset_id) references websets(id) on delete set null
  - constraint: cost_units >= 0

## Business rules enforced by the tools

- All tool calls must be attributable to exactly one workspace, derived from the authenticated api_key or server configuration; operations.workspace_id must always be set.
- If workspaces.status != 'active', then mutating operations (webset_create, enhancement_run, notification_setup) must be rejected and recorded as operations.status='failed' with an error payload.
- Quota enforcement: for each workspace and calendar month, sum(operations.cost_units) for type='exa_web_search' must not exceed workspaces.monthly_search_limit, and sum(cost_units) for type='enhancement_run' must not exceed workspaces.monthly_enhancement_limit; otherwise reject the operation.
- web_search_exa executions must create an operations row with type='exa_web_search' and persist the upstream request/response into operations.request and operations.result.
- websets_manager must implement its sub-actions by creating/updating websets, webset_items, and operations records; any added URLs must upsert into webset_items enforcing unique(webset_id, url).
- Enhancements must be stored only in webset_items.enhancements and webset_items.enhanced_at; enhancement_run must record a corresponding operations row and set status transitions correctly.
- When a webset_item is removed (status='removed'), it must not appear in webset_search results unless an explicit include_removed flag is present in operations.request (stored behavior).
- Deleting a webset (status='deleted') must soft-hide it from all reads and must cascade-delete (or mark removed) its items; DB-level fk on delete cascade applies for physical deletes, but the API should prefer soft-delete via status.
- websets_guide is read-only and must not mutate any collections; it may read aggregated metadata (counts, recent operations) but cannot create/update rows.