# Zotero MCP — local MCP environment

This backend mirrors a user’s Zotero library into a queryable store so the MCP tools can search items/notes, list collections/tags, fetch item metadata/fulltext/children, and create notes. It also tracks sync state and write operations (e.g., creating notes, batch tag updates) as jobs with auditable status and error details.

Repository: https://github.com/54yyyu/zotero-mcp
Homepage: https://smithery.ai/server/@54yyyu/zotero-mcp

## Datastore

- `libraries.json` — Represents a connected Zotero library (user or group) and its sync/auth state. All items, collections, tags, and notes belong to exactly one library. (12 rows; fields: ['id', 'zotero_library_type', 'zotero_library_id', 'display_name', 'status', 'api_base_url', 'access_token_ciphertext', 'last_sync_at', 'last_sync_cursor', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'revoked', 'error']
  - constraint: unique(zotero_library_type, zotero_library_id)
  - constraint: status in ('active','paused','revoked','error')
  - constraint: api_base_url = 'https://api.zotero.org'
- `collections.json` — Zotero collections (folders) within a library, including hierarchy. (20 rows; fields: ['id', 'library_id', 'zotero_key', 'name', 'parent_collection_id', 'version', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(library_id, zotero_key)
  - constraint: version is null or version >= 0
  - constraint: parent_collection_id is null or parent_collection_id != id
- `items.json` — All Zotero items including top-level bibliographic items, attachments, and notes. Stores metadata, fulltext (where available), and parent/child relationships. (33 rows; fields: ['id', 'library_id', 'zotero_key', 'item_type', 'parent_item_id', 'title', 'creators', 'date', 'publication_title', 'doi', 'url', 'abstract_note', 'metadata_json', 'note_html', 'annotation_json', 'fulltext_text', 'fulltext_indexed_at', 'version', 'deleted_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(library_id, zotero_key)
  - constraint: version is null or version >= 0
  - constraint: deleted_at is null or status = 'deleted'
  - constraint: parent_item_id is null or parent_item_id != id
- `item_collections.json` — Join table mapping items into collections (an item may belong to multiple collections). Supports listing collection items. (33 rows; fields: ['id', 'library_id', 'collection_id', 'item_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(collection_id, item_id)
  - constraint: collection_id and item_id must reference rows with same library_id as item_collections.library_id
- `tags.json` — Tags used in a library and their assignment to items. Supports listing tags and batch updating tags across items. (35 rows; fields: ['id', 'library_id', 'name', 'color', 'created_at', 'updated_at', 'item_tags'])
  - lifecycle `n/a`: []
  - constraint: unique(library_id, name)
  - constraint: color is null or matches /^#[0-9A-Fa-f]{6}$/
  - constraint: item_tags[*].item_id references items.id and item_tags[*].tag_id references tags.id
  - constraint: unique(item_tags.item_id, item_tags.tag_id) for active assignments per library
- `operations.json` — Auditable record of user/tool actions (searches, advanced searches, tag batch updates, note creation) and their outcomes. Enables debugging and enforcing rate/size limits. (38 rows; fields: ['id', 'library_id', 'op_type', 'request_params_json', 'status', 'result_summary_json', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: finished_at is null or started_at is not null
  - constraint: if status in ('succeeded','failed','cancelled') then finished_at is not null
  - constraint: if status = 'failed' then error_code is not null

## Business rules enforced by the tools

- All reads/writes must be scoped to exactly one libraries.id; cross-library joins are rejected (e.g., items.library_id must match collections.library_id when listing collection items).
- zotero_get_item_metadata/fulltext/children must resolve the item by (library_id, zotero_key); if status='deleted' return NOT_FOUND unless explicitly requested by internal tooling.
- zotero_get_collections returns collections where status='active' ordered by name, preserving hierarchy via parent_collection_id.
- zotero_get_collection_items returns items joined through item_collections where item_collections.status='active' and items.status='active'.
- zotero_get_recent returns items.status='active' ordered by created_at desc (or Zotero version desc if available), limited by server default (e.g., 50) and capped at a hard max (e.g., 200).
- zotero_search_items and zotero_advanced_search query items over title/creators/date/publication_title/doi/url/abstract_note/metadata_json and optionally fulltext_text; results must exclude item_type in ('attachment','annotation') unless explicitly included by server defaults.
- zotero_get_item_children returns items where parent_item_id points to the resolved parent and status='active', grouped by item_type (attachment, note, annotation, other).
- zotero_get_notes returns items where item_type='note' and status='active'; when filtering by parent item, parent_item_id must reference an active bibliographic item.
- zotero_search_notes searches within note_html (and title) for item_type='note' and status='active'.
- zotero_get_annotations returns items where item_type='annotation' and status='active'; if a specific parent is implied, filter by parent_item_id; annotation_json must be non-null.
- zotero_get_tags returns distinct tags for the library along with counts of active item_tags assignments; tags.name is case-sensitive unique per library (or normalized consistently if configured).
- zotero_create_note creates a new items row with item_type='note', parent_item_id set, note_html provided, status='active', and a new zotero_key assigned after upstream Zotero API acknowledgement; operation must be recorded in operations with op_type='create_note'.
- zotero_batch_update_tags must be executed as an operation with op_type='batch_update_tags'; it may only add/remove tags by creating/updating tags.item_tags entries and must not modify items outside the search scope computed at execution time.
- Rate limiting/quota can be enforced per library by limiting operations created per minute; exceeding limits forces operations.status='failed' with error_code='RATE_LIMITED'.
- Status transitions for libraries/collections/items/item_collections/operations must follow the declared transition maps; any other transition is rejected.