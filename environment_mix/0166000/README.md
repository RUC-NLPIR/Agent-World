# Outline Server — local MCP environment

This backend stores Outline-like knowledge base content: collections (folders/spaces) and documents (pages) that belong to collections and can be searched, moved, updated, or deleted. The main workflows are collection lifecycle management and document lifecycle management, including full-text search over document content and titles.

Repository: https://github.com/lekt9/mcp-outline
Homepage: https://smithery.ai/server/@lekt9/mcp-outline

## Datastore

- `workspaces.json` — Tenant container for collections and documents. Even if the MCP server is single-tenant, the production-shaped model keeps a workspace to scope uniqueness, permissions, and search. (12 rows; fields: ['id', 'name', 'slug', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name <> ''
  - constraint: slug <> ''
- `collections.json` — Top-level containers grouping documents. Implements create/get/list/update/delete collection tools. (12 rows; fields: ['id', 'workspace_id', 'name', 'description', 'color', 'icon', 'position', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name) where status <> 'deleted'
  - constraint: name <> ''
  - constraint: position >= 0
- `documents.json` — Documents (pages) that live inside collections. Supports create/get/list/update/delete/move and provides source-of-truth for search. (35 rows; fields: ['id', 'workspace_id', 'collection_id', 'parent_document_id', 'title', 'text', 'version', 'published_at', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['draft', 'published', 'archived', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(collection_id) references collections(id) on delete restrict
  - constraint: fk(parent_document_id) references documents(id) on delete set null
  - constraint: title <> ''
- `document_revisions.json` — Immutable change history for documents to support updates, auditing, and safe rollbacks. Updated on update_document and move_document operations. (31 rows; fields: ['id', 'document_id', 'workspace_id', 'version', 'title', 'text', 'collection_id', 'parent_document_id', 'created_at'])
  - constraint: fk(document_id) references documents(id) on delete cascade
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(collection_id) references collections(id) on delete restrict
  - constraint: unique(document_id, version)
- `document_search_index.json` — Search-optimized representation of documents for search_documents; stores tokenized/normalized fields and metadata needed for ranking. In practice backed by a full-text index, but modeled here as a table the API can query. (35 rows; fields: ['id', 'document_id', 'workspace_id', 'collection_id', 'title_normalized', 'content_normalized', 'last_indexed_version', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: fk(document_id) references documents(id) on delete cascade
  - constraint: unique(document_id)
  - constraint: last_indexed_version >= 1
  - constraint: workspace_id must equal documents.workspace_id for the referenced document_id

## Business rules enforced by the tools

- create_collection inserts collections row with status='active', position set to max(position)+1 within workspace if not provided, and must enforce unique(workspace_id,name) among non-deleted collections.
- update_collection may change name/description/color/icon/position/status but may not transition status outside the declared lifecycle transitions.
- delete_collection performs a soft delete by setting status='deleted' and deleted_at=now; it must be rejected if the collection has any documents with status <> 'deleted' (or must soft-delete/migrate them in the same transaction).
- create_document inserts documents row with version=1, status='draft' unless explicitly published by server policy; also inserts document_revisions version=1 and creates/updates document_search_index to status='active'.
- update_document must increment documents.version by 1 per successful update and append a document_revisions row capturing the pre-update or post-update snapshot (implementation choice), and mark document_search_index as 'stale' until reindexed in the same transaction or asynchronously.
- move_document changes documents.collection_id (and optionally parent_document_id) and must ensure the target collection exists, is in same workspace, and is not status='deleted'; it must append a document_revisions row capturing the move and update document_search_index.collection_id accordingly.
- delete_document performs a soft delete by setting documents.status='deleted' and deleted_at=now; it must also set document_search_index.status='deleted'.
- get_document returns the documents row by id scoped to workspace, excluding status='deleted' by default unless an internal flag is used.
- list_documents returns documents filtered by collection_id (and workspace_id), ordered by updated_at desc or position rules; deleted documents are excluded.
- search_documents queries document_search_index constrained by workspace_id (and optionally collection_id) and returns matching documents ordered by a ranking computed from title/content match; only documents with documents.status in ('draft','published','archived') and search_index.status='active' are eligible.
- FK integrity is enforced for all references; cross-tenant references are forbidden (workspace_id consistency constraints).