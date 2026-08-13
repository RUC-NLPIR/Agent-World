# ClickUp Task Integration Server — local MCP environment

This backend models a ClickUp integration server that mirrors a workspace hierarchy (workspace→spaces→folders→lists), tasks (with tags, comments, attachments, custom fields), time tracking, and ClickUp Docs (documents and pages). Tools operate by resolving entities by id or by name within a container scope, then creating/updating/moving/deleting tasks/lists/folders/docs, and reading hierarchy, members, tags, comments, and time entries.

Repository: https://github.com/arspesk/clickup-mcp-server
Homepage: https://smithery.ai/server/@arspesk/clickup-mcp-server

## Datastore

- `workspaces.json` — Connected ClickUp workspaces (teams) and their core cached hierarchy endpoints. Also stores the integration's notion of workspace members sync watermark. (12 rows; fields: ['workspace_id', 'clickup_team_id', 'name', 'timezone', 'hierarchy_cache', 'members_cache', 'members_synced_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(clickup_team_id)
  - constraint: status in ('active','disabled')
  - constraint: created_at is required
  - constraint: updated_at is required
- `containers.json` — Unified hierarchy nodes for SPACE, FOLDER, LIST, and special containers used by ClickUp Docs (EVERYTHING, WORKSPACE). Enables resolving entities by name within a scope for list/folder/space operations and doc parent targeting. (32 rows; fields: ['container_id', 'workspace_id', 'clickup_container_id', 'type', 'parent_container_id', 'name', 'content', 'override_statuses', 'archived', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(workspace_id) references workspaces(workspace_id)
  - constraint: fk(parent_container_id) references containers(container_id)
  - constraint: type in ('SPACE','FOLDER','LIST','WORKSPACE','EVERYTHING')
  - constraint: archived in (true,false)
- `tasks.json` — ClickUp tasks and related sub-entities (tags, comments, attachments, custom fields, and bulk operations metadata). Supports resolving by taskId or taskName scoped to a list. (35 rows; fields: ['task_id', 'workspace_id', 'list_container_id', 'clickup_task_id', 'clickup_custom_id', 'name', 'description', 'status_name', 'priority', 'due_date', 'start_date', 'assignee_user_ids', 'parent_clickup_task_id', 'custom_fields', 'tags', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(workspace_id) references workspaces(workspace_id)
  - constraint: fk(list_container_id) references containers(container_id)
  - constraint: unique(workspace_id, clickup_task_id)
  - constraint: unique(workspace_id, clickup_custom_id) where clickup_custom_id is not null
- `task_activity.json` — Child tables for task comments, attachments, and tag associations. Also stores space tag catalog for validation of add/remove tag operations and space tag listing. (37 rows; fields: ['activity_id', 'workspace_id', 'type', 'task_id', 'clickup_task_id', 'space_container_id', 'clickup_comment_id', 'comment_text', 'comment_assignee_clickup_user_id', 'notify_all', 'clickup_attachment_id', 'filename', 'source_type', 'source_ref', 'size_bytes', 'tag_name', 'tag_fg_color', 'tag_bg_color', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(workspace_id) references workspaces(workspace_id)
  - constraint: fk(task_id) references tasks(task_id)
  - constraint: fk(space_container_id) references containers(container_id)
  - constraint: type in ('TASK_COMMENT','TASK_ATTACHMENT','TASK_TAG','SPACE_TAG')
- `time_and_docs.json` — Tracks time entries (including running timer semantics) and ClickUp Docs (documents and pages). A unified table is used with type discriminator to stay within collection limits while still modeling separate lifecycles. (35 rows; fields: ['entity_id', 'workspace_id', 'type', 'task_id', 'clickup_task_id', 'clickup_time_entry_id', 'start_time', 'end_time', 'duration_seconds', 'billable', 'description', 'tags', 'clickup_user_id', 'document_id', 'clickup_document_id', 'clickup_page_id', 'title', 'content', 'content_format', 'parent_container_id', 'parent_type_code', 'visibility', 'create_page', 'depth', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'running', 'stopped', 'deleted']
  - constraint: fk(workspace_id) references workspaces(workspace_id)
  - constraint: fk(task_id) references tasks(task_id)
  - constraint: fk(parent_container_id) references containers(container_id)
  - constraint: type in ('TIME_ENTRY','DOCUMENT','DOCUMENT_PAGE','RUNNING_TIMER_POINTER')

## Business rules enforced by the tools

- get_workspace_hierarchy reads workspaces.hierarchy_cache when fresh; if stale or null, it must refresh containers from ClickUp and update hierarchy_cache and updated_at.
- When resolving by name (taskName/listName/folderName/spaceName), the resolver must require a disambiguating scope when names are not guaranteed unique: (taskName without listName) may match multiple tasks; (folderName requires space scope); tools must error on multiple matches.
- create_task requires name and exactly one list target (listId or listName resolvable to a LIST container). If parent is provided, parent task must exist and be in same workspace.
- update_task requires at least one mutable field; it must only update provided fields. If taskName is used without listName, the operation must fail if multiple matches exist.
- move_task updates tasks.list_container_id to the destination LIST container. If destination list has incompatible statuses, backend must accept that status_name may change/reset after vendor move and refresh task state.
- duplicate_task creates a new tasks row with a new clickup_task_id; it may copy tags/custom_fields/assignees/dates/description from the source task, but must not copy internal task_id.
- delete_task and delete_list and delete_folder are irreversible: status must transition to 'deleted' and must not transition back; cascading deletes must mark descendant entities as deleted (list→tasks; folder→lists→tasks).
- get_task_comments paginates by (start, startId) over task_activity rows of type TASK_COMMENT ordered by created_at then activity_id; vendor ids are stored in clickup_comment_id when available.
- create_task_comment requires commentText and a resolvable task. If notifyAll is true, notify_all must be stored and sent to vendor; assignee if present must be a valid workspace member id.
- attach_task_file must enforce size limits: base64 uploads must be <= 10MB; store only metadata and a source_ref, never base64 payload. Chunked uploads must create multiple TASK_ATTACHMENT rows or a single row with source_type='chunked' and a chunk upload reference.
- create_bulk_tasks/update_bulk_tasks/move_bulk_tasks/delete_bulk_tasks must record each task mutation individually and must be idempotent per clickup_task_id where possible; tasks must remain consistent even if partial failures occur.
- get_workspace_tasks requires at least one filter: tags, list_ids, folder_ids, space_ids, statuses, assignees, or date filters; query must be scoped to one workspace_id and must not return deleted tasks.
- get_space_tags returns SPACE_TAG rows for a space_container_id (type SPACE). add_tag_to_task must validate the tag exists in SPACE_TAG for the task's space before creating TASK_TAG; remove_tag_from_task must delete only the TASK_TAG association.
- get_workspace_members/find_member_by_name/resolve_assignees read from workspaces.members_cache; if cache is older than a configured TTL, backend should refresh before resolving to reduce false negatives.
- get_task_time_entries returns TIME_ENTRY rows for the task ordered by start_time desc; it must include running entry if present.
- start_time_tracking must enforce: at most one running TIME_ENTRY per (workspace_id, clickup_user_id). Starting a new timer while another is running must stop the old one first or fail, matching server configuration.
- stop_time_tracking finds the single running TIME_ENTRY for the current user/workspace and transitions status running→stopped, setting end_time and duration_seconds.
- add_time_entry creates a TIME_ENTRY with status='stopped' and requires start_time and duration_seconds > 0; end_time must equal start_time + duration_seconds.
- delete_time_entry transitions TIME_ENTRY to deleted; it must not delete task rows.
- get_current_time_entry returns the running TIME_ENTRY for the current user/workspace or null if none.
- create_list/create_list_in_folder create a containers row with type='LIST' and appropriate parent_container_id (SPACE or FOLDER). update_list updates only specified fields; delete_list transitions to deleted and cascades tasks to deleted.
- create_folder creates a containers row with type='FOLDER' parented to a SPACE; override_statuses, if provided, must be a valid array payload. delete_folder cascades to lists and tasks.
- create_document requires title/name, parent info (parent_container_id and parent_type_code), visibility, and create_page flag. list_documents filters by parent_type (SPACE/FOLDER/LIST/EVERYTHING/WORKSPACE) and/or parent container.
- list_document_pages and get_document_pages operate on DOCUMENT_PAGE rows linked by document_id; if no pageIds provided, return all pages. update_document_page must support replace vs append: replace overwrites content; append concatenates while preserving content_format.
- All tools must only operate on entities in status != 'deleted'; attempting to mutate deleted entities must return a not-found style error.