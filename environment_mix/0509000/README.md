# ClickUp Task Integration Server — local MCP environment

This backend persists a cached mirror of a ClickUp workspace hierarchy (spaces/folders/lists), tasks (including custom fields, tags, comments, attachments, and time entries), and an audit log of integration operations. The main workflows are: resolve human-friendly identifiers (names) to stable ClickUp IDs, perform task/list/folder/time-entry mutations, and support workspace-wide task search/filtering and pagination.

Repository: https://github.com/aukik/clickup-mcp-server
Homepage: https://smithery.ai/server/@aukik/clickup-mcp-server

## Datastore

- `workspaces.json` — Represents a single connected ClickUp Workspace (Team) and its cached hierarchy metadata used to resolve space/folder/list names to IDs. (12 rows; fields: ['id', 'clickup_team_id', 'name', 'status', 'default_time_zone', 'hierarchy_snapshot', 'last_hierarchy_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'read_only', 'disabled']
  - constraint: unique(clickup_team_id)
  - constraint: status in ('active','read_only','disabled')
- `hierarchy_entities.json` — Normalized ClickUp hierarchy nodes: spaces, folders, and lists. Enables resolving by ID or name and supports create/get/update/delete for lists and folders plus tag lookups at space level. (33 rows; fields: ['id', 'workspace_id', 'entity_type', 'clickup_id', 'parent_entity_id', 'space_clickup_id', 'name', 'content', 'archived', 'override_statuses', 'status', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(workspace_id, entity_type, clickup_id)
  - constraint: entity_type in ('space','folder','list')
  - constraint: archived = true implies status in ('archived','deleted')
  - constraint: parent_entity_id is null iff entity_type='space'
- `tasks.json` — Tasks and related task-level details sufficient to implement create/get/update/move/duplicate/delete, workspace-wide task retrieval, comments, attachments, tags, and custom fields. (40 rows; fields: ['id', 'workspace_id', 'clickup_task_id', 'custom_id', 'list_entity_id', 'parent_task_id', 'name', 'description', 'status_text', 'priority', 'due_date', 'start_date', 'assignee_clickup_user_ids', 'custom_fields', 'tag_names', 'status', 'last_synced_at', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(workspace_id, clickup_task_id)
  - constraint: priority is null or (priority >= 1 and priority <= 5)
  - constraint: parent_task_id is null or parent_task_id != id
  - constraint: FK(list_entity_id) must reference hierarchy_entities where entity_type='list' and status!='deleted'
- `task_activity.json` — Child tables for task comments, attachments, and tag associations. Stored together as an activity stream for pagination and auditing, while still containing typed fields required by tools. (35 rows; fields: ['id', 'workspace_id', 'task_id', 'activity_type', 'clickup_comment_id', 'comment_text', 'comment_assignee_clickup_user_id', 'comment_notify_all', 'attachment_clickup_file_id', 'attachment_filename', 'attachment_source_type', 'attachment_url', 'tag_space_entity_id', 'tag_name', 'cursor_id', 'occurred_at', 'status', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: index(task_id, activity_type, occurred_at)
  - constraint: for activity_type='comment': comment_text is not null
  - constraint: for activity_type='comment': cursor_id is not null
  - constraint: for activity_type='attachment': attachment_source_type is not null
- `time_entries.json` — Tracks ClickUp time tracking entries, including the single currently running entry per workspace/user context, manual entries, tags, billable flag, and lifecycle for start/stop/delete operations. (32 rows; fields: ['id', 'workspace_id', 'task_id', 'clickup_time_entry_id', 'clickup_user_id', 'description', 'billable', 'tag_names', 'start_at', 'end_at', 'duration_ms', 'is_running', 'source', 'status', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'stopped', 'deleted']
  - constraint: unique(workspace_id, clickup_time_entry_id)
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: end_at is null implies status='running' and is_running=true
  - constraint: end_at is not null implies status='stopped' and is_running=false
- `integration_operations.json` — Audit log for all tool calls (single and bulk) including resolution by name, pagination cursors used, and bulk batch outcomes. Enables debugging and enforcing safety rules around ambiguous name-based operations. (38 rows; fields: ['id', 'workspace_id', 'tool_name', 'operation_type', 'request_params', 'resolved_clickup_ids', 'bulk_count', 'succeeded_count', 'failed_count', 'status', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'in_progress', 'succeeded', 'failed', 'rejected']
  - constraint: bulk_count is null or bulk_count >= 0
  - constraint: succeeded_count is null or succeeded_count >= 0
  - constraint: failed_count is null or failed_count >= 0
  - constraint: if tool_name like '%bulk%' then bulk_count is not null

## Business rules enforced by the tools

- get_workspace_hierarchy returns workspaces.hierarchy_snapshot if last_hierarchy_sync_at is fresh; otherwise it refreshes hierarchy_entities (spaces/folders/lists) and updates hierarchy_snapshot + last_hierarchy_sync_at.
- Any tool accepting listId/listName resolves to hierarchy_entities where entity_type='list' and status='active'; if listName matches multiple lists in the workspace, the operation must be rejected unless further scoping (spaceName/spaceId/folderName/folderId) is provided by the tool implementation.
- Any tool accepting folderId/folderName resolves to hierarchy_entities where entity_type='folder' and status='active'; folderName without space scope must be rejected if multiple folders share the same name across spaces.
- Task name-based resolution (taskName) must be scoped to a list when performing bulk updates/moves/deletes; if taskName resolution yields 0 or >1 candidates, the operation must be rejected and logged with integration_operations.status='rejected'.
- create_task requires a target list (listId or resolvable listName) and a non-empty name; it creates tasks.status='active' and persists custom_fields exactly as provided (array of {id,value}) in tasks.custom_fields.
- get_task with subtasks=true returns the task plus all tasks where parent_task_id references the resolved task; subtasks are never returned across different lists unless ClickUp reports them that way in raw payload.
- update_task requires at least one mutable field; only provided fields are updated. If custom_fields are provided, they replace or upsert per custom field id within tasks.custom_fields (implementation-defined but must be consistent).
- move_task changes tasks.list_entity_id to the destination list; if destination list has incompatible statuses, the implementation may clear or remap tasks.status_text, and must record the final value from ClickUp in tasks.raw/status_text.
- duplicate_task creates a new tasks row with a new clickup_task_id and copies eligible fields (name/description/status_text/priority/dates/assignees/custom_fields/tag associations) as ClickUp returns; parent_task_id is null unless explicitly duplicated as subtask by ClickUp.
- delete_task and delete_list/delete_folder are permanent operations: tasks.status or hierarchy_entities.status must transition to 'deleted' and must not transition back; the integration must retain audit rows in integration_operations.
- get_task_comments reads task_activity rows where activity_type='comment' ordered by occurred_at ascending/descending as required; pagination uses start (offset-like) and/or cursor_id (startId) to continue from a stable point.
- create_task_comment inserts a task_activity row with activity_type='comment' and must set cursor_id to the returned clickup_comment_id (or a generated stable cursor if missing).
- attach_task_file must enforce max base64 payload size of 10MB; for URL attachments only http/https schemes are allowed; for local path sources, only absolute paths are allowed and must be readable by the server process.
- get_space_tags returns tags known in the space; tags are derived from ClickUp and may be stored denormalized in hierarchy_entities.raw for the space and/or inferred from tasks.tag_names; add/remove tag operations must verify the tag exists in the target space before mutating associations.
- add_tag_to_task and remove_tag_from_task must add an activity row (tag_added/tag_removed) and update tasks.tag_names to reflect the latest set; removing a tag only removes the association and never deletes the tag definition.
- get_workspace_tasks requires at least one filter (tags, list_ids, folder_ids, space_ids, statuses, assignees, or a date filter). If no filters are supplied, the request must be rejected and logged.
- Workspace-wide task filtering must only return tasks.status='active' and must support filtering by: list_entity_id (lists), list's parent folder/space (via hierarchy_entities relationships), status_text, assignee_clickup_user_ids contains, tag_names contains, and due/start date ranges.
- start_time_tracking must stop any existing running entry in the same workspace (time_entries where is_running=true) before creating a new running entry, or reject if server policy disallows implicit stop; in all cases, the invariant 'at most one running entry per workspace' must hold.
- stop_time_tracking must find the single running time entry (status='running' and is_running=true) and transition it to stopped by setting end_at and duration_ms; if none exists it must return a not-found style response.
- add_time_entry creates a stopped/manual time entry with required start_at and duration_ms and computed end_at = start_at + duration_ms; duration_ms must be >= 0.
- delete_time_entry transitions the matching time_entries row to status='deleted' and must not physically remove the row to preserve auditability.
- get_current_time_entry returns the single time_entries row where status='running' and is_running=true for the workspace, or null if none.
- All tool invocations must create an integration_operations row; write operations in a disabled workspace must be rejected (status='rejected'), and in read_only workspace only read tools may proceed.