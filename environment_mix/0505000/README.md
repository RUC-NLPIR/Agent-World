# Notion API Integration Server — local MCP environment

This backend stores a local mirror of Notion objects (pages, databases, blocks, and page properties) plus operational metadata for an integration server (connections, sync state, request logs). Main workflows: verify/authenticate a Notion connection, create/query databases and pages (including todos), and manage block trees (add/list/get/update/delete) while tracking lifecycle states like archived/deleted.

Repository: https://github.com/Darth-Ginger/notion-api-mcp
Homepage: https://smithery.ai/server/@Darth-Ginger/notion-api-mcp

## Datastore

- `notion_connections.json` — Represents a configured Notion integration connection (workspace + token) used by all tools; includes verification status and operational metadata. (12 rows; fields: ['id', 'name', 'notion_api_base_url', 'notion_api_version', 'encrypted_access_token', 'notion_workspace_id', 'bot_user_id', 'configured_todos_database_id', 'status', 'last_verified_at', 'last_verification_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(name)
  - constraint: notion_api_base_url like 'https://%'
  - constraint: notion_api_version <> ''
  - constraint: status in ('active','disabled','revoked')
- `notion_pages.json` — Local mirror/registry for Notion pages, including todo pages and generic pages; supports page CRUD, archiving/restoring, and property access. (35 rows; fields: ['id', 'connection_id', 'notion_page_id', 'parent_type', 'parent_notion_id', 'notion_database_id', 'title', 'icon', 'cover', 'archived', 'status', 'raw_notion', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(connection_id, notion_page_id)
  - constraint: archived = true implies status = 'archived' OR status = 'deleted'
  - constraint: parent_type in ('page_id','database_id','workspace')
  - constraint: parent_type = 'workspace' implies parent_notion_id is null
- `notion_page_properties.json` — Stores page property values (or references to property items) to support get_page_property and todo filtering/search without re-fetching full pages. (31 rows; fields: ['id', 'connection_id', 'page_id', 'notion_property_id', 'property_name', 'property_type', 'value', 'notion_property_item_id', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `property_type`: ['title', 'rich_text', 'number', 'select', 'multi_select', 'status', 'date', 'people', 'checkbox', 'url', 'email', 'phone_number', 'relation', 'rollup', 'formula', 'files', 'created_time', 'last_edited_time', 'created_by', 'last_edited_by']
  - constraint: unique(connection_id, page_id, notion_property_id)
  - constraint: property_name <> ''
  - constraint: property_type in ('title','rich_text','number','select','multi_select','status','date','people','checkbox','url','email','phone_number','relation','rollup','formula','files','created_time','last_edited_time','created_by','last_edited_by')
- `notion_databases.json` — Local mirror/registry for Notion databases created/queried by the server; stores schema and query defaults for todo workflows. (38 rows; fields: ['id', 'connection_id', 'notion_database_id', 'parent_page_notion_id', 'title', 'schema', 'archived', 'status', 'raw_notion', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(connection_id, notion_database_id)
  - constraint: schema is not null
  - constraint: parent_page_notion_id <> ''
  - constraint: archived = true implies status = 'archived'
- `notion_blocks.json` — Stores Notion block tree data to support add_content_blocks, get_block_content, list_block_children, update_block_content, and delete_block. (19 rows; fields: ['id', 'connection_id', 'notion_block_id', 'owner_type', 'owner_notion_id', 'parent_block_id', 'page_id', 'block_type', 'content', 'has_children', 'position_index', 'archived', 'status', 'raw_notion', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(connection_id, notion_block_id)
  - constraint: owner_type in ('page','block')
  - constraint: position_index is null OR position_index >= 0
  - constraint: archived = true implies status = 'archived' OR status = 'deleted'
- `notion_request_logs.json` — Operational log of Notion API requests made by tool calls; supports auditing, debugging, and lightweight rate/quota enforcement. (36 rows; fields: ['id', 'connection_id', 'tool_name', 'notion_method', 'notion_path', 'request_body', 'response_status', 'response_body', 'duration_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `response_status`: []
  - constraint: duration_ms >= 0
  - constraint: response_status >= 100 AND response_status <= 599
  - constraint: tool_name in ('create_page','get_page','update_page','archive_page','restore_page','get_page_property','add_todo','search_todos','create_database','query_database','verify_connection','get_database_info','add_content_blocks','get_block_content','list_block_children','update_block_content','delete_block')

## Business rules enforced by the tools

- All tools must execute under exactly one active notion_connections row; if status != 'active', tool calls must fail with an authorization/connection error and must not mutate local mirrors.
- verify_connection must perform a Notion API call; on success it must set notion_connections.last_verified_at to now, clear last_verification_error, and may populate notion_workspace_id and bot_user_id; on failure it must set last_verification_error and must not change status.
- create_page must insert/update notion_pages with a unique (connection_id, notion_page_id), set status='active', archived=false, and store the returned Notion JSON in raw_notion.
- get_page must read-through cache: if notion_pages.raw_notion is missing or stale, it should refresh from Notion and update raw_notion and last_synced_at; it must not return pages with status='deleted' unless explicitly requested by internal maintenance.
- update_page must not allow updates when notion_pages.status in ('archived','deleted'); it must PATCH Notion then update notion_pages.raw_notion, title (if derivable), and updated_at.
- archive_page must transition notion_pages.status from 'active' to 'archived' and set archived=true; it must be idempotent if already archived.
- restore_page must transition notion_pages.status from 'archived' to 'active' and set archived=false; it must fail if status='deleted'.
- get_page_property must resolve the target property by (page_id/notion_page_id + notion_property_id/property_name); if the property is paginated in Notion, notion_property_item_id must be stored/used; the resulting value must be persisted to notion_page_properties.value and last_synced_at.
- create_database must insert/update notion_databases with unique (connection_id, notion_database_id), persist schema, set status='active', archived=false, and may set notion_connections.configured_todos_database_id when the created DB is intended for todos.
- get_database_info must return the database referenced by notion_connections.configured_todos_database_id; if missing, it must fail with a configuration error.
- query_database must only query a database with notion_databases.status='active' and must enforce that filter/sort JSON conforms to Notion API expectations; query results should upsert notion_pages rows for returned page ids (as database rows).
- add_todo must create a page in the configured todos database (notion_connections.configured_todos_database_id) and must persist the resulting page in notion_pages plus relevant properties in notion_page_properties (e.g., title, status, due, tags) to support search_todos.
- search_todos must execute primarily via Notion database query; additionally, it may use notion_page_properties for local filtering/caching, but must not return pages where notion_pages.status in ('archived','deleted') unless explicitly filtered for archived.
- add_content_blocks must create child blocks under a specified page/block and record them in notion_blocks; if positioning is provided by the server, it must write position_index values that are unique among siblings (owner_type, owner_notion_id) within a narrow range and must be non-negative.
- get_block_content must read-through cache notion_blocks.raw_notion; if missing/stale it must fetch from Notion and update raw_notion and last_synced_at.
- list_block_children must return blocks ordered by position_index when available; if Notion returns ordering, the server must update position_index to match and keep (parent_block_id, position_index) unique for non-null position_index.
- update_block_content must not update notion_blocks rows where status in ('archived','deleted'); it must PATCH Notion and then update notion_blocks.content/raw_notion and updated_at.
- delete_block must soft-delete: set notion_blocks.status='deleted' and archived=true after successful Notion deletion/archive; repeated deletes must be idempotent.
- Every tool invocation that calls Notion must create a notion_request_logs row with tool_name, method, path, response_status and duration_ms; request_body/response_body must be redacted/truncated to avoid storing secrets or large payloads.