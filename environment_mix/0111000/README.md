# Notion — local MCP environment

This backend stores a Notion-like workspace graph of databases, pages, blocks, and threaded comments, plus query/search activity for pagination and filtering. Core workflows: manage databases and pages (CRUD), manipulate hierarchical block content (read/append/update), and search/query content with comments retrieval at page or block scope.

Repository: https://github.com/smithery-ai/mcp-servers
Homepage: https://smithery.ai/server/@smithery/notion

## Datastore

- `databases.json` — Databases that live under a parent page and define a schema (properties) used by pages/rows inside the database. (18 rows; fields: ['id', 'workspace_id', 'parent_page_id', 'title', 'description', 'properties_schema', 'icon', 'cover', 'is_inline', 'archived', 'status', 'created_by_user_id', 'last_edited_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: fk(databases.parent_page_id) -> pages.id
  - constraint: title <> ''
  - constraint: properties_schema must be valid JSON object
  - constraint: archived = (status = 'archived')
- `pages.json` — Pages that can live under a parent page or inside a database (as a row). Stores metadata and properties; block content lives in blocks. (18 rows; fields: ['id', 'workspace_id', 'parent_type', 'parent_page_id', 'parent_database_id', 'title', 'properties', 'icon', 'cover', 'archived', 'status', 'created_by_user_id', 'last_edited_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: exactly one of parent_page_id, parent_database_id must be non-null and must match parent_type
  - constraint: fk(pages.parent_page_id) -> pages.id
  - constraint: fk(pages.parent_database_id) -> databases.id
  - constraint: properties must be valid JSON object
- `blocks.json` — Hierarchical content blocks belonging to a page (rooted at the page) or nested under other blocks. Supports append and update operations and child pagination. (19 rows; fields: ['id', 'workspace_id', 'page_id', 'parent_block_id', 'type', 'data', 'has_children', 'sort_index', 'archived', 'status', 'created_by_user_id', 'last_edited_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: fk(blocks.page_id) -> pages.id
  - constraint: fk(blocks.parent_block_id) -> blocks.id
  - constraint: data must be valid JSON object
  - constraint: sort_index >= 0
- `comments.json` — Threaded comments attached to either a page or a specific block. Supports listing comments and creating new comments/replies. (19 rows; fields: ['id', 'workspace_id', 'discussion_id', 'page_id', 'block_id', 'parent_comment_id', 'author_user_id', 'rich_text', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'deleted']
  - constraint: fk(comments.page_id) -> pages.id
  - constraint: fk(comments.block_id) -> blocks.id
  - constraint: fk(comments.parent_comment_id) -> comments.id
  - constraint: block_id is null OR (block_id references a block with same page_id)
- `search_index.json` — Materialized search index entries for pages and databases to support fast title/content search. Content is derived from pages.properties and blocks.data; used by the search tool. (18 rows; fields: ['id', 'workspace_id', 'object_type', 'page_id', 'database_id', 'title_text', 'content_text', 'token_vector', 'last_indexed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'stale', 'disabled']
  - constraint: exactly one of page_id, database_id must be non-null and must match object_type
  - constraint: fk(search_index.page_id) -> pages.id
  - constraint: fk(search_index.database_id) -> databases.id
  - constraint: unique(workspace_id, object_type, page_id, database_id)

## Business rules enforced by the tools

- list-databases returns databases where workspace_id matches caller and status != 'deleted' (if implemented) ordered by updated_at desc; typically filters out archived unless explicitly requested by API layer.
- create-database requires parent_page_id to reference an active page in the same workspace; initializes properties_schema with at least a title property; inserts/updates a corresponding search_index row with object_type='database'.
- update-database may change title/description/properties_schema; if properties_schema changes, existing pages with parent_database_id must have properties validated/migrated or rejected if incompatible (API typically rejects invalid property updates).
- query-database operates over pages where parent_type='database' and parent_database_id matches; filtering/sorting are applied against pages.properties and pages.created_at/updated_at; pagination uses stable ordering (e.g., updated_at,id) and a cursor derived from those fields.
- get_page reads from pages by id and workspace_id and returns metadata/properties only; it must not return blocks content.
- create-page inserts into pages with either (parent_type='page', parent_page_id) or (parent_type='database', parent_database_id); when created under a database, pages.properties must conform to databases.properties_schema; also creates an initial root block set optionally via subsequent append.
- update_page updates pages.properties (and derived pages.title if applicable) and bumps updated_at; it must validate properties against the database schema when parent_type='database'; updates related search_index row (status becomes 'stale' until reindexed).
- get-block reads a single block by id ensuring workspace_id matches; for child_page/child_database blocks, the API layer may additionally resolve referenced entities but storage remains in blocks.data.
- get-block-children lists blocks by (page_id, parent_block_id) with ordering by sort_index then id; supports pagination via (sort_index,id) cursor semantics.
- append-block-children inserts new blocks with parent_block_id pointing to the target parent; assigns sort_index values greater than existing max for that parent; sets parent's has_children=true; marks page search_index status='stale'.
- update-block mutates blocks.data for the specified block and updates updated_at; it must preserve type-specific invariants (e.g., to_do.checked is boolean, code.language is string); marks page search_index status='stale'.
- search queries search_index for matching title_text/content_text within workspace and returns referenced pages/databases (metadata only). Results must not include entities with status in ('deleted') and should typically exclude archived unless requested by API layer.
- get-comments lists comments for a given page_id (and optionally discussion_id if used by API) where status='published'; ordering is created_at asc within discussion_id.
- get-all-page-comments returns all comments where page_id matches, including those with block_id not null; it may require joining blocks to ensure block.page_id matches comment.page_id when block_id is present.
- create-comment requires either a page_id or a block_id; if block_id is provided, page_id must match the block's page_id; if discussion_id is provided it must refer to an existing thread on the same page; otherwise a new discussion_id is generated; inserts comment with status='published'.