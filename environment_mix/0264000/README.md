# ClickUp MCP Server — local MCP environment

This backend mirrors a ClickUp workspace (team) hierarchy (spaces, folders, lists) and the operational objects users interact with (tasks, comments, tags, time entries). The main workflows are: resolving entities by id or name (often ambiguous), creating/updating/moving/duplicating/deleting tasks and containers, tagging tasks, and tracking time (single running timer per user/workspace) with manual and automatic time entries.

Repository: https://github.com/TaazKareem/clickup-mcp-server
Homepage: https://smithery.ai/server/@taazkareem/clickup-mcp-server

## Datastore

- `workspaces.json` — Represents a ClickUp Team/Workspace and its hierarchy roots. Used for workspace-wide reads like hierarchy and members. (12 rows; fields: ['id', 'clickup_team_id', 'name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(clickup_team_id)
  - constraint: name <> ''
- `members.json` — Workspace members (ClickUp users). Supports get_workspace_members, find_member_by_name, and resolve_assignees. (31 rows; fields: ['id', 'workspace_id', 'clickup_user_id', 'username', 'email', 'full_name', 'role', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(workspace_id, clickup_user_id)
  - constraint: email is null or email like '%@%'
  - constraint: full_name <> ''
- `containers.json` — Unified hierarchy nodes for spaces, folders, and lists. Enables get_workspace_hierarchy plus create/get/update/delete for lists and folders and space tag lookup by space. (35 rows; fields: ['id', 'workspace_id', 'type', 'parent_id', 'clickup_id', 'name', 'content', 'archived', 'due_date', 'priority', 'assignee_member_id', 'override_statuses', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(workspace_id, type, clickup_id)
  - constraint: parent_id is null implies type = 'space'
  - constraint: type = 'folder' implies parent_id references a 'space' container
  - constraint: type = 'list' implies parent_id references a 'space' or 'folder' container
- `tasks.json` — Tasks and related associations. Supports create/get/update/move/duplicate/delete tasks, bulk operations, comments, file attachments metadata, and tag assignment via join rows. (34 rows; fields: ['id', 'workspace_id', 'list_container_id', 'parent_task_id', 'clickup_task_id', 'custom_task_id', 'name', 'description', 'status_name', 'priority', 'start_date', 'due_date', 'time_estimate_ms', 'assignee_clickup_user_ids', 'custom_fields', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(workspace_id, clickup_task_id)
  - constraint: custom_task_id is null or unique(workspace_id, custom_task_id)
  - constraint: name <> ''
  - constraint: priority is null or (priority >= 0 and priority <= 4)
- `task_activity.json` — Task comments, attachments, tags, and time entries (including running timer). Supports get/create comments, attach file, add/remove tags, get workspace tags, and time tracking tools. (32 rows; fields: ['id', 'workspace_id', 'task_id', 'space_container_id', 'kind', 'clickup_id', 'author_member_id', 'assignee_member_id', 'notify_all', 'body_text', 'attachment_filename', 'attachment_source_type', 'attachment_url', 'attachment_size_bytes', 'tag_name', 'tag_color', 'billable', 'time_entry_description', 'time_entry_tags', 'start_time', 'end_time', 'duration_ms', 'running', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: kind='comment' implies task_id is not null and body_text is not null and body_text <> ''
  - constraint: kind='attachment' implies task_id is not null and attachment_source_type is not null
  - constraint: kind='attachment' implies attachment_size_bytes is null or attachment_size_bytes <= 10485760 when attachment_source_type='base64'
  - constraint: kind='space_tag' implies space_container_id references containers.id where containers.type='space' and tag_name is not null

## Business rules enforced by the tools

- get_workspace_hierarchy returns all containers for a workspace grouped by type with parent-child relationships; only containers.status='active' are returned.
- Entity resolution by name must be scoped when possible: listName resolution searches containers where type='list' and status='active'; folderName resolution searches containers where type='folder' and status='active' and requires a space scope when the API tool indicates space disambiguation.
- When a tool uses taskId, the system must match against tasks.clickup_task_id OR tasks.custom_task_id; if both match different tasks, the request must fail with an ambiguity error.
- When a tool uses taskName without listName, the system must search tasks by name within the workspace and fail if multiple active matches exist (rather than choosing arbitrarily).
- create_task requires a resolvable destination list (listId preferred else listName) and a non-empty name; if parent is supplied, parent_task_id must exist and be in the same workspace.
- update_task requires at least one mutable field change; if no changes are provided, the request must fail validation.
- move_task changes tasks.list_container_id to the destination list. If the current status_name is not valid in the destination list workflow (not modeled here), the implementation must reset status_name to null or a destination default and record updated_at.
- duplicate_task creates a new tasks row copying description, dates, priority, time_estimate_ms, custom_fields, assignee_clickup_user_ids, and tag associations (task_activity kind='task_tag') into new rows; it must not copy comments, attachments, or time entries.
- delete_task sets tasks.status='deleted' and must also set related task_activity rows (comments, attachments, task_tag, time_entry) to status='deleted' to prevent further reads.
- create_bulk_tasks, update_bulk_tasks, move_bulk_tasks, delete_bulk_tasks are executed as repeated single-item operations with per-item success/failure reporting; they must enforce the same validation rules as the single-item tools.
- get_workspace_tasks requires at least one filter input; filters map to tasks.list_container_id (list_ids), container ancestry (folder_ids/space_ids via containers.parent_id chains), tasks.status_name (statuses), and tags via task_activity(kind='task_tag', tag_name). Only tasks.status='active' are returned.
- get_task_comments returns task_activity rows where kind='comment' and status='active' for the resolved task, ordered by created_at ascending, with pagination implemented via (created_at, id) cursor using start/startId semantics.
- create_task_comment inserts a task_activity row kind='comment' with body_text and optional notify_all/assignee_member_id; author_member_id must be set to the calling user when available.
- attach_task_file inserts a task_activity row kind='attachment' with attachment_source_type and metadata; base64 uploads must enforce size <= 10MB based on decoded bytes.
- get_space_tags returns task_activity rows where kind='space_tag' and status='active' for the resolved space.
- add_tag_to_task requires the tag to exist as a space_tag in the task's space; then it inserts kind='task_tag' for that task; duplicates are prevented by unique constraint.
- remove_tag_from_task deletes (soft-deletes) the task_activity kind='task_tag' row for that task/tag if it exists; it must not delete the underlying space_tag row.
- start_time_tracking creates a kind='time_entry' row with running=true for the calling member; it must fail if another active running time_entry exists for the same (workspace_id, author_member_id).
- stop_time_tracking finds the active running time_entry for the calling member, sets end_time=now, duration_ms=end_time-start_time, running=false, and allows optional description/tags updates; if none running, it must return null or a not-running error per tool behavior.
- add_time_entry creates a completed kind='time_entry' row with start_time and duration_ms required, end_time=start_time+duration; running must be false.
- get_current_time_entry returns the single active time_entry row with running=true for the calling member in the workspace (or null).
- delete_time_entry soft-deletes the matching task_activity row where kind='time_entry' and clickup_id matches the provided time entry id; if not found, return not found.