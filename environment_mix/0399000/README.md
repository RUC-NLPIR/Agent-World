# Notion MCP Server — local MCP environment

This backend stores a local projection of Notion workspaces (pages, databases, and blocks) plus an operation log that the MCP server uses to execute single and batch mutations and to support search/query. Core workflows are: create/update/archive/restore pages, create/update/query databases, CRUD-style block operations (append/update/delete), and batching mixed block operations with transactional semantics and auditing.

Repository: https://github.com/awkoy/notion-mcp-server
Homepage: https://smithery.ai/server/@awkoy/notion-mcp-server

## Datastore

- `workspaces.json` — Represents a connected Notion workspace (tenant) and its sync/search configuration as seen by the MCP server. (12 rows; fields: ['id', 'notion_workspace_id', 'display_name', 'status', 'default_page_id', 'search_indexing_enabled', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(notion_workspace_id)
  - constraint: display_name <> ''
  - constraint: if status = 'revoked' then search_indexing_enabled = false
- `pages.json` — Stores Notion pages (including database rows) with properties and minimal searchable title projection. (34 rows; fields: ['id', 'workspace_id', 'notion_page_id', 'parent_type', 'parent_page_id', 'parent_database_id', 'title', 'properties', 'icon', 'cover', 'status', 'archived_at', 'last_notion_edited_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(workspace_id, notion_page_id)
  - constraint: parent_type in ('workspace','page','database')
  - constraint: if parent_type='page' then parent_page_id is not null and parent_database_id is null
  - constraint: if parent_type='database' then parent_database_id is not null and parent_page_id is null
- `databases.json` — Stores Notion databases and their schema, plus denormalized title for search_pages and support for query_database. (36 rows; fields: ['id', 'workspace_id', 'notion_database_id', 'parent_page_id', 'title', 'schema', 'status', 'archived_at', 'last_notion_edited_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(workspace_id, notion_database_id)
  - constraint: if status='archived' then archived_at is not null
  - constraint: if status='active' then archived_at is null
- `blocks.json` — Stores Notion blocks and their hierarchy for retrieve_block, retrieve_block_children, append_block_children, update_block, and delete_block (trash). (33 rows; fields: ['id', 'workspace_id', 'notion_block_id', 'owner_type', 'page_id', 'parent_block_id', 'type', 'content', 'has_children', 'position', 'status', 'trashed_at', 'last_notion_edited_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'trashed']
  - constraint: unique(workspace_id, notion_block_id)
  - constraint: if parent_block_id is not null then page_id is not null
  - constraint: if position is not null then position >= 0
  - constraint: if status='trashed' then trashed_at is not null
- `operations.json` — Write-ahead log and batch execution tracking for MCP tool calls (single and batch). Used for idempotency, retries, auditability, and enforcing batch semantics. (44 rows; fields: ['id', 'workspace_id', 'tool_name', 'request', 'response', 'target_notion_id', 'batch_parent_operation_id', 'batch_index', 'status', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: if batch_parent_operation_id is not null then batch_index is not null and batch_index >= 0
  - constraint: if status in ('succeeded','failed','cancelled') then finished_at is not null
  - constraint: if status = 'running' then started_at is not null
  - constraint: length(tool_name) > 0

## Business rules enforced by the tools

- All tool executions must create an operations row capturing tool_name and the raw request; on completion they must set status and persist either response (on success) or error_code/error_message (on failure).
- create_page must insert a pages row (status='active') and may also insert an initial root block tree under that page; if a parent is not provided in the request, workspaces.default_page_id must be used, otherwise the operation fails.
- archive_page must transition pages.status from 'active' to 'archived' and set archived_at; restore_page must transition from 'archived' to 'active' and clear archived_at.
- update_page_properties must update pages.properties and refresh pages.title if the title property changed; it must update last_notion_edited_at from the Notion response when available.
- search_pages must search across pages.title and databases.title within a workspace, excluding entities with status='archived', returning both pages and databases ordered by a relevance score (implementation-defined).
- create_database must insert a databases row (status='active') and store schema; update_database must update databases.schema and title if changed.
- query_database must read from Notion and may optionally materialize/refresh pages that represent database rows; any materialized rows must have parent_type='database' and parent_database_id set.
- append_block_children must create blocks rows for each appended child with parent_block_id pointing to the target parent block and with monotonically increasing position within that parent; it must set has_children=true on the parent block.
- retrieve_block must return a block by notion_block_id scoped to workspace_id; retrieve_block_children must return child blocks where parent_block_id matches, ordered by position then created_at.
- update_block must update blocks.content (and possibly blocks.type if Notion indicates a type change) and set last_notion_edited_at.
- delete_block must transition blocks.status from 'active' to 'trashed' and set trashed_at; trashed blocks must be excluded from retrieve_block_children by default unless the request explicitly asks for trashed (not present in tool surface, so default is excluded).
- batch_append_block_children, batch_update_blocks, batch_delete_blocks, and batch_mixed_operations must create a parent operations row (tool_name=the batch tool) and one child operations row per sub-operation linked via batch_parent_operation_id and batch_index.
- Batch execution must be atomic per parent operation when feasible: if any child operation fails, the parent operation status must be 'failed' and the response must include per-item statuses; partial success is allowed only if explicitly chosen by server policy, but it must still be recorded per child operation.
- Foreign key integrity must be enforced: workspace_id must exist on all pages/databases/blocks/operations; parent_page_id/parent_database_id/parent_block_id references must exist when provided and must belong to the same workspace.
- Uniqueness must be enforced for external ids within a workspace: (workspace_id, notion_page_id), (workspace_id, notion_database_id), and (workspace_id, notion_block_id) are unique; upserts must update existing rows instead of inserting duplicates.
- Status transitions must follow the lifecycle definitions; direct writes that violate transitions (e.g., trashed->active for blocks) must be rejected.