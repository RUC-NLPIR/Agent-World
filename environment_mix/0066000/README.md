# Notion API Integration Server — local MCP environment

This backend stores a local mirror of Notion workspaces (pages, databases, blocks) plus a specialized Todo model implemented as database-backed pages. The main workflows are: verifying/maintaining a Notion integration connection, creating/updating/archiving pages and blocks, and creating/querying databases and todos with filter/sort support while tracking sync state and lifecycle status.

Repository: https://github.com/HitmanLy007/notion-api-mcp
Homepage: https://smithery.ai/server/@HitmanLy007/notion-api-mcp

## Datastore

- `integrations.json` — Represents a configured Notion integration/connection for a tenant. Holds auth material, connection health, and default database configuration used by todo and database tools. (12 rows; fields: ['id', 'workspace_name', 'notion_workspace_id', 'notion_bot_id', 'auth_type', 'encrypted_access_token', 'token_fingerprint', 'notion_api_base_url', 'notion_api_version', 'default_todos_database_notion_id', 'default_parent_page_notion_id', 'last_verified_at', 'last_error_code', 'last_error_message', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'degraded', 'revoked', 'disabled']
  - constraint: unique(token_fingerprint)
  - constraint: notion_api_base_url != ''
  - constraint: notion_api_version != ''
- `pages.json` — Local mirror of Notion pages (including database row pages such as todos). Supports create/get/update/archive/restore and property retrieval by storing properties JSON and sync metadata. (18 rows; fields: ['id', 'integration_id', 'notion_page_id', 'parent_type', 'parent_notion_id', 'in_database_notion_id', 'title_plaintext', 'icon', 'cover', 'properties', 'archived', 'status', 'notion_created_time', 'notion_last_edited_time', 'last_synced_at', 'last_sync_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted_remote', 'sync_error']
  - constraint: unique(integration_id, notion_page_id)
  - constraint: archived = true implies status in ('archived','deleted_remote','sync_error') OR status='archived'
  - constraint: parent_type != 'workspace' implies parent_notion_id is not null
- `databases.json` — Local mirror of Notion databases and their schema. Supports create_database, query_database, and get_database_info (including the configured todos database). (20 rows; fields: ['id', 'integration_id', 'notion_database_id', 'parent_page_notion_id', 'title_plaintext', 'schema', 'archived', 'status', 'notion_created_time', 'notion_last_edited_time', 'last_synced_at', 'last_sync_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted_remote', 'sync_error']
  - constraint: unique(integration_id, notion_database_id)
  - constraint: schema is not null
- `blocks.json` — Local mirror of Notion blocks for pages and other blocks. Supports add_content_blocks (including positioning), get_block_content, list_block_children, update_block_content, and delete_block. (18 rows; fields: ['id', 'integration_id', 'notion_block_id', 'root_page_id', 'parent_block_id', 'parent_notion_block_id', 'block_type', 'has_children', 'position_index', 'content', 'archived', 'status', 'notion_created_time', 'notion_last_edited_time', 'last_synced_at', 'last_sync_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted_remote', 'sync_error']
  - constraint: unique(integration_id, notion_block_id)
  - constraint: position_index is null OR position_index >= 0
  - constraint: parent_block_id is null OR root_page_id is not null
- `todos.json` — First-class Todo model mapped to Notion database row pages. Enables advanced filtering/search over normalized fields while retaining the full Notion page payload in pages.properties. (18 rows; fields: ['id', 'integration_id', 'database_id', 'page_id', 'notion_page_id', 'title', 'description', 'due_at', 'priority', 'tags', 'assignees', 'completed', 'completed_at', 'archived', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'completed', 'archived']
  - constraint: unique(integration_id, notion_page_id)
  - constraint: title != ''
  - constraint: completed = true implies status = 'completed' OR status='archived'
  - constraint: completed_at is null OR completed = true
- `request_logs.json` — Audit trail of tool invocations and Notion API interactions for debugging, rate limiting, and support. Used by all tools implicitly even though the tool surface does not expose it. (19 rows; fields: ['id', 'integration_id', 'tool_name', 'request_payload', 'notion_endpoint', 'notion_http_status', 'success', 'error_code', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `success`: ['true', 'false']
  - constraint: duration_ms >= 0
  - constraint: notion_http_status is null OR (notion_http_status >= 100 AND notion_http_status <= 599)

## Business rules enforced by the tools

- All tools must resolve an active integration; if integrations.status in ('disabled','revoked') then any mutating tool (create/update/archive/restore/add_content_blocks/update_block_content/delete_block/add_todo/create_database) must be rejected.
- verify_connection performs a Notion API call (e.g., users/me). On success: integrations.last_verified_at is set and integrations.status transitions to 'active'. On auth failure: integrations.status transitions to 'revoked' and last_error_* is recorded.
- create_page must insert a pages row with status='active' and archived=false after successful Notion page creation; uniqueness (integration_id, notion_page_id) must be enforced for idempotency.
- get_page must read pages by notion_page_id (or internal id) and, if stale or missing, fetch from Notion then upsert pages.last_synced_at, properties, notion_last_edited_time.
- update_page must only operate on pages.status != 'deleted_remote'. After successful update, pages.properties and notion_last_edited_time must be refreshed and pages.status must remain consistent with pages.archived.
- archive_page sets pages.archived=true and pages.status='archived'. restore_page sets pages.archived=false and pages.status='active'. These transitions must be reflected in todos.archived/status when the page is a todo row.
- get_page_property must return a property item from pages.properties; if a property item requires pagination/lookup in Notion, the server must fetch it and update pages.last_synced_at.
- create_database must create a databases row with schema stored in databases.schema and status='active' after successful Notion creation; uniqueness (integration_id, notion_database_id) enforced.
- get_database_info returns the configured default todos database if integrations.default_todos_database_notion_id is set; otherwise it must return the most recently created active database or an explicit configuration error.
- query_database must translate filters/sorts to Notion and may optionally cache resulting pages in pages and todos. Any cached page rows created must have in_database_notion_id set to the queried database notion id.
- add_todo must create a Notion database row page in the todos database, then upsert pages and insert todos with page_id referencing the created page. todos.title is required; completed defaults to false; status defaults to 'open'.
- search_todos must support advanced filtering using normalized todos fields (completed/status/due_at/priority/tags/assignees/title text) and may combine with Notion query results; returned items must map back to todos.page_id/pages.notion_page_id.
- add_content_blocks appends or inserts blocks under a parent (page or block). It must create blocks rows for each created block with correct parent_notion_block_id and position_index values; uniqueness (integration_id, notion_block_id) enforced.
- list_block_children returns blocks under a given parent; if local cache is missing, it must fetch from Notion and upsert blocks with parent linkage and position_index.
- update_block_content must reject updates when blocks.status='deleted_remote'. On success, blocks.content and notion_last_edited_time must be updated.
- delete_block must archive (soft-delete) the block in Notion; locally blocks.archived=true and blocks.status='archived'. Hard deletes are not allowed to preserve auditability.
- For any Notion API failure, the system must create a request_logs row with success=false and update the relevant entity (page/database/block) status to 'sync_error' with last_sync_error populated when appropriate.
- Foreign key integrity: pages.integration_id, databases.integration_id, blocks.integration_id, todos.integration_id must reference integrations.id; todos.page_id must reference pages.id; blocks.parent_block_id must reference blocks.id when set; all such references must exist at commit time.
- Quota/rate limiting (implementation-level): the server must not exceed Notion rate limits; when limit is hit, it must back off and record request_logs.error_code='rate_limited' without corrupting entity state.