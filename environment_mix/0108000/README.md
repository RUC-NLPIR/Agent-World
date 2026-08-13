# Notion — local MCP environment

This backend stores a Notion-like workspace graph: users/bots, databases (schemas), pages (records), blocks (content tree), and comments. Primary workflows are: authenticate as an integration/bot, list users, create/update/query databases and pages, read/append/update/delete blocks, and create/retrieve comments, with search and database queries supported via indexed fields on pages/databases.

Repository: https://github.com/makenotion/notion-mcp-server
Homepage: https://smithery.ai/server/@makenotion/notion-mcp-server

## Datastore

- `notion_users.json` — Human users and bot users (integrations) that act within a workspace. Serves get-self/get-user/get-users and attribution fields across all content. (29 rows; fields: ['id', 'workspace_id', 'type', 'email', 'name', 'avatar_url', 'bot_owner_user_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deactivated']
  - constraint: fk(workspace_id) -> workspaces.id
  - constraint: unique(workspace_id, email) where email is not null
  - constraint: type='bot' implies email is null OR email is optional
  - constraint: type='bot' implies bot_owner_user_id is null OR references a person user in same workspace
- `auth_tokens.json` — Integration/bot tokens used by the API. Enables get-self resolution and authorization checks across tools. (12 rows; fields: ['id', 'workspace_id', 'token_hash', 'bot_user_id', 'name', 'scopes', 'last_used_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: fk(workspace_id) -> workspaces.id
  - constraint: fk(bot_user_id) -> notion_users.id
  - constraint: unique(token_hash)
  - constraint: status in ('active','revoked')
- `databases.json` — Notion databases (schema containers) with property definitions. Serves create/update/retrieve database and database query. (12 rows; fields: ['id', 'workspace_id', 'parent_type', 'parent_page_id', 'title', 'description', 'properties_schema', 'status', 'created_by_user_id', 'last_edited_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: fk(workspace_id) -> workspaces.id
  - constraint: fk(parent_page_id) -> pages.id
  - constraint: fk(created_by_user_id) -> notion_users.id
  - constraint: fk(last_edited_by_user_id) -> notion_users.id
- `pages.json` — Notion pages which may belong to a database (as rows) or be standalone, and store property values. Serves create/retrieve/update page, retrieve page property, search, and database query results. (35 rows; fields: ['id', 'workspace_id', 'parent_type', 'parent_database_id', 'parent_page_id', 'properties', 'icon', 'cover', 'url', 'archived', 'trashed', 'status', 'created_by_user_id', 'last_edited_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'trashed']
  - constraint: fk(workspace_id) -> workspaces.id
  - constraint: fk(parent_database_id) -> databases.id
  - constraint: fk(parent_page_id) -> pages.id
  - constraint: fk(created_by_user_id) -> notion_users.id
- `blocks.json` — Content blocks forming a tree under pages and other blocks. Serves retrieve block, update block, delete block, retrieve children, and append children. (36 rows; fields: ['id', 'workspace_id', 'page_id', 'parent_block_id', 'type', 'content', 'has_children', 'children_sort', 'archived', 'status', 'created_by_user_id', 'last_edited_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: fk(workspace_id) -> workspaces.id
  - constraint: fk(page_id) -> pages.id
  - constraint: fk(parent_block_id) -> blocks.id
  - constraint: fk(created_by_user_id) -> notion_users.id
- `comments.json` — Page comments (and optionally inline discussion anchored to a block). Serves create/retrieve comment. (19 rows; fields: ['id', 'workspace_id', 'page_id', 'discussion_id', 'parent_comment_id', 'anchor_block_id', 'rich_text', 'created_by_user_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'deleted']
  - constraint: fk(workspace_id) -> workspaces.id
  - constraint: fk(page_id) -> pages.id
  - constraint: fk(anchor_block_id) -> blocks.id
  - constraint: fk(created_by_user_id) -> notion_users.id

## Business rules enforced by the tools

- Authorization: every tool call is associated with exactly one auth_tokens row in status='active'; all reads/writes must be limited to records where workspace_id matches the token.workspace_id.
- API-get-self returns the notion_users row referenced by auth_tokens.bot_user_id for the calling token.
- API-get-user retrieves a notion_users row by id and must be in the caller's workspace; API-get-users lists all notion_users in the workspace with status='active' by default.
- API-create-a-database creates a databases row with parent_type/workspace or parent_type/page; parent_type='page' requires parent_page_id and that page.status != 'trashed'.
- API-update-a-database may mutate title/description/properties_schema/status; status transitions must follow databases.lifecycle.transitions; schema updates must not invalidate existing pages.properties (reject or migrate).
- API-retrieve-a-database returns the databases row only if status != 'archived' unless the API chooses to include archived; in all cases must match workspace_id.
- API-post-database-query reads pages where parent_database_id equals the queried database id; if the database is archived, queries are still allowed only if the token has read scope; filtering/sorting is applied against pages.properties and pages.updated_at; results exclude pages with status='trashed' unless explicitly requested.
- API-post-search searches across pages and databases in the workspace using indexed fields derived from pages.properties (title-like fields), databases.title, and optionally block text; results must exclude status='trashed' entities by default.
- API-post-page creates a pages row; parent_type must be one of ('database','page','workspace') and the corresponding parent foreign key must be valid; if parent_type='database', properties must satisfy databases.properties_schema (required properties, type correctness).
- API-retrieve-a-page returns a pages row by id, including properties and metadata; must be in workspace and not status='trashed' unless explicitly allowed.
- API-patch-page updates pages.properties and/or archived/trashed; status must remain consistent with archived/trashed booleans; last_edited_by_user_id and updated_at must change on successful mutation.
- API-retrieve-a-page-property reads a single property item from pages.properties; the property key must exist, and if the property is paginated (e.g., relation/rollup), the API must support cursoring at the application layer even if stored as a JSON structure.
- API-retrieve-a-block reads blocks by id; must be in workspace; archived blocks may be returned but clearly marked archived=true.
- API-update-a-block mutates blocks.content for the given type and/or archived flag; type changes are disallowed once created (reject) to match typical Notion semantics; last_edited_by_user_id and updated_at must update.
- API-delete-a-block performs a soft delete by setting blocks.archived=true and status='archived' (no hard delete).
- API-get-block-children lists blocks where parent_block_id equals the requested block id (or page-root blocks via a separate route in the API layer), ordered by children_sort ascending; excludes archived children by default.
- API-patch-block-children appends new blocks under a parent block by inserting blocks rows with increasing children_sort; it must atomically set parent.has_children=true when at least one active child exists.
- API-create-a-comment inserts a comments row with status='published'; page_id must exist and not be trashed; if anchor_block_id is provided it must belong to the same page.
- API-retrieve-a-comment returns the comments row by id if in workspace; deleted comments may be returned with status='deleted' but must not expose rich_text if policy requires redaction.