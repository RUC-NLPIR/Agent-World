# Google Drive — local MCP environment

This backend models a Google Drive-like filesystem with files/folders, shared drives, permissions, and threaded comments. It supports listing/searching, reading metadata/content, creating/updating/moving/copying/trashing items, managing sharing, tracking versions, and producing a changes feed with page tokens for incremental sync.

Repository: https://github.com/rishipradeep-think41/google-drive-mcp
Homepage: https://smithery.ai/server/@rishipradeep-think41/google-drive-mcp

## Datastore

- `drive_items.json` — Represents both files and folders (and shortcuts) in My Drive or Shared Drives, including metadata, trashing, starring, locking, and content pointers. Serves listing, search, metadata, content read, create/upload/append, rename, star, restore, delete, copy, move, shortcut create, shared drive files listing, and storage breakdown/quota aggregation. (18 rows; fields: ['id', 'shared_drive_id', 'owner_principal', 'name', 'mime_type', 'item_type', 'shortcut_target_item_id', 'description', 'starred', 'locked', 'trashed_at', 'status', 'size_bytes', 'content_blob_id', 'content_text_encoding', 'md5_checksum', 'modified_by_principal', 'modified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'trashed', 'deleted']
  - constraint: item_type in ('file','folder','shortcut')
  - constraint: mime_type <> ''
  - constraint: name <> ''
  - constraint: size_bytes >= 0
- `drive_item_parents.json` — Join table mapping items to parent folders (supports multiple parents). Serves drive_folder_children, drive_file_move, drive_create parents, copy/move batch operations, and integrity for folder structure. (18 rows; fields: ['id', 'item_id', 'parent_folder_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: unique(item_id, parent_folder_id)
  - constraint: FK item_id -> drive_items.id ON DELETE CASCADE
  - constraint: FK parent_folder_id -> drive_items.id ON DELETE RESTRICT
  - constraint: parent folder must have drive_items.item_type='folder'
- `shared_drives.json` — Shared Drive containers and metadata. Serves drive_shared_drives_list, drive_shared_drive_get, create/update/delete, and scoped listing/search within a shared drive. (18 rows; fields: ['id', 'name', 'color_rgb', 'hidden', 'status', 'created_by_principal', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: name <> ''
  - constraint: color_rgb is null OR color_rgb matches /^#?[0-9A-Fa-f]{6}$/
  - constraint: unique(created_by_principal, name) where status='active'
  - constraint: on delete: status='deleted' (soft delete); cannot hard delete if drive_items exist unless cascade policy applied
- `permissions.json` — Sharing/ACL entries on items (user/group/domain/anyone). Serves drive_share, drive_permissions_list, drive_permission_update, drive_permission_delete, drive_permission_add_domain, drive_permission_add_anyone, and drive_batch_update_permissions. (18 rows; fields: ['id', 'item_id', 'type', 'role', 'email_address', 'domain', 'allow_discovery', 'status', 'created_by_principal', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: role in ('reader','commenter','writer','organizer')
  - constraint: type in ('user','group','domain','anyone')
  - constraint: type in ('user','group') implies email_address is not null and domain is null
  - constraint: type='domain' implies domain is not null and email_address is null
- `comments.json` — Stores file comments and replies in a single threaded table. Serves drive_comment, drive_file_list_comments, drive_file_delete_comment, drive_file_reply_to_comment, drive_file_list_replies, and drive_file_delete_reply. (18 rows; fields: ['id', 'item_id', 'parent_comment_id', 'author_principal', 'content', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: content <> ''
  - constraint: FK item_id -> drive_items.id ON DELETE CASCADE
  - constraint: FK parent_comment_id -> comments.id ON DELETE CASCADE
  - constraint: parent_comment_id is null OR (select item_id of parent)=item_id (reply must be on same file) [enforced at write-time]
- `file_versions.json` — Immutable versions for file content and change feed tokens. Serves drive_versions_list, drive_versions_delete, drive_upload/update content, drive_file_content retrieval (via current version pointer), and drive_changes incremental sync through change tokens derived from sequence ids. (18 rows; fields: ['id', 'item_id', 'version_number', 'blob_id', 'mime_type', 'size_bytes', 'md5_checksum', 'created_by_principal', 'created_at', 'updated_at', 'status', 'change_sequence'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: FK item_id -> drive_items.id ON DELETE CASCADE
  - constraint: unique(item_id, version_number)
  - constraint: version_number >= 1
  - constraint: size_bytes >= 0

## Business rules enforced by the tools

- drive_file_metadata(fileId) reads drive_items by id where status!='deleted'.
- drive_file_content(fileId) returns bytes from blob referenced by drive_items.content_blob_id; only valid when drive_items.item_type='file' and status='active'.
- drive_folder_children(folderId, pageToken, pageSize) lists children via drive_item_parents where parent_folder_id=folderId and child drive_items.status!='deleted'; folderId must reference a drive_items row with item_type='folder'.
- drive_search(query, pageToken, pageSize) executes a fulltext search over drive_items(name, description) scoped to the caller's accessible items (owner_principal or permissions/shared drive membership); excludes status='deleted' by default.
- drive_create(name, mimeType, parents) inserts drive_items (folder if mimeType indicates folder else file) with status='active'; for each parent in parents inserts drive_item_parents; all parents must be folders and in same drive scope (same shared_drive_id or both NULL).
- drive_upload(fileId?, data, mimeType) when fileId is provided: creates a new file_versions row (version_number = prior max + 1, change_sequence = global + 1) and updates drive_items.content_blob_id/size_bytes/mime_type/modified_at; when fileId is absent: creates a new file item plus version 1.
- drive_append_text(fileId, text) requires file mime_type to be text/* or application/json (configurable); appends by creating a new version and updating drive_items pointers/size.
- drive_delete(fileId, permanent=false) if permanent=false transitions drive_items.status active->trashed and sets trashed_at; if permanent=true transitions to deleted and removes parent links and permissions/comments via FK cascades; deleted items are not returned in listings/search.
- drive_restore(fileId) transitions drive_items.status trashed->active and clears trashed_at.
- drive_star(fileId, starredFlag) toggles drive_items.starred (tool surface omits params; implementation supplies).
- drive_rename(fileId, newName) updates drive_items.name and modified_at; newName must be non-empty.
- drive_copy(fileId, destinationFolderId?, newName?) creates a new drive_items row duplicating metadata, parent links (or destination folder), and for files creates a new file_versions row referencing copied blob (copy-on-write allowed); shortcut copies preserve target reference.
- drive_file_move(fileId, destinationFolderId, removeFromCurrentFolders) inserts new drive_item_parents relation to destination; if removeFromCurrentFolders=true deletes other parent relations for that item; destination must be a folder and in same drive scope.
- drive_shortcut_create(targetFileId, parents, name?) creates a drive_items row with item_type='shortcut' and shortcut_target_item_id set; parents must be folders in same drive scope.
- drive_file_lock(fileId, lockedFlag) sets drive_items.locked; when locked=true, mutations that change content/metadata (upload/append/rename/move) are rejected unless caller has writer/organizer.
- drive_share(fileId, role, type, emailAddress?) creates or upserts an active permissions row for item_id=fileId; for type='anyone' and 'domain' emailAddress must be null.
- drive_permissions_list(fileId) returns active permissions rows for item.
- drive_permission_update(permissionId, role, ...) updates an active permissions row; cannot update revoked permissions.
- drive_permission_delete(permissionId) transitions permissions.status active->revoked.
- drive_permission_add_domain(fileId, domain, role) creates an active permissions row with type='domain'.
- drive_permission_add_anyone(fileId, role, allowDiscovery?) creates an active permissions row with type='anyone'.
- drive_comment(fileId, content) inserts an active comments row with parent_comment_id null.
- drive_file_reply_to_comment(fileId, commentId, content) inserts an active comments row with parent_comment_id=commentId and item_id=fileId.
- drive_file_list_comments(fileId) returns comments where item_id=fileId and parent_comment_id is null and status='active'.
- drive_file_list_replies(fileId, commentId) returns comments where parent_comment_id=commentId and status='active'.
- drive_file_delete_comment(commentId) and drive_file_delete_reply(replyId) transition comments.status to 'deleted'.
- drive_versions_list(fileId) returns file_versions where item_id=fileId and status='active' ordered by version_number desc.
- drive_versions_delete(fileId, versionId) transitions file_versions.status active->deleted; must not remove the last active version if drive_items.status='active' (or must convert file to empty with content_blob_id null).
- drive_shared_drives_list(pageSize,pageToken) returns shared_drives where created_by_principal/caller has access and status='active'; pagination uses opaque tokens derived from (created_at,id).
- drive_shared_drive_get(driveId) reads shared_drives by id where status='active'.
- drive_shared_drive_create(name,colorRgb,hidden) inserts shared_drives status='active'.
- drive_shared_drive_update(driveId, name?, colorRgb?, hidden?) updates shared_drives; cannot update deleted drives.
- drive_shared_drive_delete(driveId) transitions shared_drives.status active->deleted; items remain but become inaccessible unless policy also transitions contained drive_items to deleted/trashed (implementation choice, must be consistent).
- drive_shared_drive_files(driveId, q, orderBy, pageSize, pageToken) lists drive_items where shared_drive_id=driveId and status!='deleted' and matches optional q; supports orderBy on (name asc, modified_at desc, etc.).
- drive_storage_quota() aggregates size_bytes across caller-owned items (or accessible scope) with status='active'; returns used vs limit from configuration.
- drive_storage_breakdown(maxResults) aggregates drive_items.size_bytes by mime_type for status='active' and item_type='file', ordered desc, limited by maxResults.
- drive_batch_get_metadata(fileIds, fields) returns drive_items for provided ids; 'fields' controls projection only (no additional storage).
- drive_batch_update_permissions(operations) performs permission upserts per operation with transactional semantics per operation; invalid operations do not partially create duplicate active permissions due to unique constraint.
- drive_batch_delete(fileIds, permanent) applies drive_delete semantics to each id; if permanent=false, sets status='trashed' and trashed_at; if permanent=true sets status='deleted'.
- drive_batch_copy(operations) applies drive_copy per op; destinationFolderId nullable means keep same parents; newName optional.
- drive_batch_move(operations) applies drive_file_move per op; if removeFromCurrentFolders is omitted, defaults to true.
- drive_changes(startPageToken) treats startPageToken as an encoded integer change_sequence; returns all file_versions with change_sequence > token (plus metadata-only changes emitted as synthetic sequence increments by updating drive_items.modified_at and allocating a change_sequence in a lightweight internal mechanism); nextPageToken is max returned change_sequence.