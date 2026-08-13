# Feishu(飞书) Integration Server — local MCP environment

This backend stores Feishu tenant connections, Drive items (folders/documents), document block snapshots/operations, and media assets (images) handled by the integration server. Main workflows: connect to a tenant, browse/search Drive, read document metadata/content/blocks, mutate documents by creating/updating/deleting blocks (including batching), and upload/bind/download image media.

Repository: https://github.com/cso1z/Feishu-MCP
Homepage: https://smithery.ai/server/@cso1z/feishu-mcp

## Datastore

- `tenants.json` — Represents a connected Feishu tenant/app installation and its auth configuration used to call Feishu OpenAPI on behalf of a workspace/user. (12 rows; fields: ['id', 'feishu_tenant_key', 'app_id', 'app_secret_ciphertext', 'default_user_id', 'access_token_ciphertext', 'access_token_expires_at', 'scopes', 'status', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(feishu_tenant_key)
  - constraint: app_secret_ciphertext is encrypted-at-rest
  - constraint: access_token_expires_at must be > created_at when access_token_ciphertext is not null
- `drive_items.json` — Feishu Drive nodes (folders, documents, wiki nodes) indexed/cached by the integration for navigation, search results, and resolving tokens/URLs. (33 rows; fields: ['id', 'tenant_id', 'feishu_token', 'item_type', 'title', 'url', 'parent_item_id', 'owner_user_id', 'created_by_user_id', 'source', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'inaccessible', 'unknown']
  - constraint: foreign key(tenant_id) references tenants(id)
  - constraint: foreign key(parent_item_id) references drive_items(id)
  - constraint: unique(tenant_id, feishu_token, item_type)
  - constraint: item_type='folder' implies parent_item_id may be null only for root folder
- `documents.json` — Normalized document records for Feishu Docs that can be read/modified (metadata, derived plain text snapshot, and linkage to Drive token). Wiki nodes may resolve to a document via wiki conversion. (28 rows; fields: ['id', 'tenant_id', 'drive_item_id', 'feishu_document_id', 'doc_type', 'title', 'owner_user_id', 'permission', 'plain_text_snapshot', 'snapshot_version', 'last_content_fetched_at', 'last_blocks_fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted', 'inaccessible']
  - constraint: foreign key(tenant_id) references tenants(id)
  - constraint: foreign key(drive_item_id) references drive_items(id)
  - constraint: unique(tenant_id, feishu_document_id)
  - constraint: snapshot_version >= 0
- `document_blocks.json` — Cached block tree and per-block content metadata for Feishu documents. Used to serve get_feishu_document_blocks/get_feishu_block_content and to validate insertion/deletion positions for block mutations. (28 rows; fields: ['id', 'tenant_id', 'document_id', 'feishu_block_id', 'parent_feishu_block_id', 'block_type', 'index_in_parent', 'raw_block_payload', 'text_plain', 'heading_level', 'code_language', 'list_type', 'media_id', 'snapshot_version', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'stale']
  - constraint: foreign key(tenant_id) references tenants(id)
  - constraint: foreign key(document_id) references documents(id)
  - constraint: unique(tenant_id, document_id, feishu_block_id)
  - constraint: heading_level between 1 and 9 when not null
- `media_assets.json` — Tracks uploaded/downloaded Feishu media resources (primarily images) and their binding to document blocks, including source URL/path and upload status. (33 rows; fields: ['id', 'tenant_id', 'document_id', 'feishu_media_id', 'content_type', 'byte_size', 'sha256', 'source_kind', 'source_uri', 'bound_block_id', 'status', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'uploaded', 'bound', 'downloaded', 'failed']
  - constraint: foreign key(tenant_id) references tenants(id)
  - constraint: foreign key(document_id) references documents(id)
  - constraint: foreign key(bound_block_id) references document_blocks(id)
  - constraint: byte_size >= 0 when not null
- `operations.json` — Audit log and idempotency store for all tool invocations (read and write), including batching, to support retries, debugging, rate limiting, and mapping tool parameters to persisted actions. (39 rows; fields: ['id', 'tenant_id', 'tool_name', 'request_json', 'target_drive_item_id', 'target_document_id', 'target_block_id', 'status', 'idempotency_key', 'feishu_request_id', 'response_json', 'error_code', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign key(tenant_id) references tenants(id)
  - constraint: foreign key(target_drive_item_id) references drive_items(id)
  - constraint: foreign key(target_document_id) references documents(id)
  - constraint: foreign key(target_block_id) references document_blocks(id)

## Business rules enforced by the tools

- All tool executions must create an operations row with tool_name and request_json; successful calls should store response_json and set status=succeeded; failures set status=failed with error_code/error_message.
- convert_feishu_wiki_to_document_id must upsert a drive_items row with item_type='wiki_node' and source='wiki_convert' and then upsert the resolved documents row (unique on tenant_id+feishu_document_id).
- get_feishu_document_info/content/blocks must require an active tenants.status='active' connection; if Feishu returns not found or forbidden, mark documents.status='deleted' or 'inaccessible' respectively (and similarly drive_items.status).
- get_feishu_document_blocks refresh should set documents.snapshot_version = documents.snapshot_version + 1 and set all prior document_blocks for that document to status='stale' before upserting the new snapshot_version as status='active'.
- update_feishu_block_text may only target a document_blocks row whose block_type is one of ('text','heading','code','list_item'); otherwise reject.
- batch_create_feishu_blocks must enforce Feishu batching limits: at most 50 blocks per upstream API request; larger inputs must be split into multiple operations entries linked by the same idempotency_key prefix.
- delete_feishu_document_blocks must only delete consecutive blocks within the same parent_feishu_block_id; the server should validate this using cached index_in_parent when available, otherwise it must refetch blocks before executing.
- create_feishu_image_block must create (or identify) an image block in document_blocks with block_type='image' and then create a media_assets row status=pending; after upload it becomes uploaded with feishu_media_id, then bound with bound_block_id referencing the image block.
- upload_and_bind_image_to_block requires that the target document_blocks.block_type='image' and media_id is null (empty image block) OR is being replaced explicitly; after binding, document_blocks.media_id must equal media_assets.feishu_media_id and media_assets.status='bound'.
- get_feishu_image_resource requires a valid feishu_media_id; successful downloads should upsert media_assets with source_kind='feishu_download' and status='downloaded' and populate byte_size/content_type/sha256 when determinable.
- get_feishu_root_folder_info must upsert a drive_items row item_type='folder' for the tenant root (parent_item_id null) and mark status='active'.
- get_feishu_folder_files must upsert child drive_items rows with parent_item_id pointing at the folder; items not returned over time may be marked status='unknown' but not 'deleted' without explicit API signal.
- create_feishu_folder must insert a new drive_items row item_type='folder' with parent_item_id set to the specified parent folder and status='active'; uniqueness is enforced by (tenant_id, feishu_token, item_type) once the API returns the token.
- Any write operation that would exceed tenant rate limits should be rejected before calling Feishu; rate limit state may be derived from operations created_at counts per tenant per minute (implementation detail not stored as a separate collection here).