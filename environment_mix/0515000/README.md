# Todoist Extended MCP Server — local MCP environment

This backend stores a cached, multi-tenant representation of a user's Todoist workspace (projects, sections, tasks, labels, and comments) plus lifecycle state needed to support completion/reopen, moves, and soft-deletes. The main workflows are CRUD on these resources, searching/filtering tasks, and performing move/complete/reopen actions while keeping referential integrity between projects/sections/tasks and their associated labels/comments.

Repository: https://github.com/kydycode/todoist-mcp-server-ext
Homepage: https://smithery.ai/server/@kydycode/todoist-mcp-server-ext

## Datastore

- `todoist_projects.json` — Projects synced/managed via Todoist. Projects contain sections and tasks. (30 rows; fields: ['id', 'todoist_project_id', 'name', 'color', 'is_favorite', 'view_style', 'parent_todoist_project_id', 'order_index', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(todoist_project_id)
  - constraint: order_index >= 0
  - constraint: status = 'deleted' implies deleted_at is not null
  - constraint: status != 'deleted' implies deleted_at is null
- `todoist_sections.json` — Sections within projects; tasks may belong to a section. (31 rows; fields: ['id', 'todoist_section_id', 'todoist_project_id', 'name', 'order_index', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(todoist_section_id)
  - constraint: order_index >= 0
  - constraint: status = 'deleted' implies deleted_at is not null
  - constraint: status != 'deleted' implies deleted_at is null
- `todoist_labels.json` — Labels/tags that can be attached to tasks. Stored separately from task-label mapping for fast lookup and CRUD. (30 rows; fields: ['id', 'todoist_label_id', 'name', 'color', 'order_index', 'is_favorite', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(todoist_label_id)
  - constraint: unique(name) where status != 'deleted'
  - constraint: order_index >= 0
  - constraint: status = 'deleted' implies deleted_at is not null
- `todoist_tasks.json` — Tasks (items) including parent/subtask hierarchy, completion lifecycle, scheduling, and label association (stored as label ids array for query convenience). (33 rows; fields: ['id', 'todoist_task_id', 'content', 'description', 'priority', 'todoist_project_id', 'todoist_section_id', 'parent_todoist_task_id', 'order_index', 'due', 'deadline', 'labels_todoist_ids', 'assignee_todoist_id', 'url', 'status', 'completed_at', 'deleted_at', 'quick_add_raw', 'quick_add_parse_result', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: unique(todoist_task_id)
  - constraint: priority between 1 and 4
  - constraint: order_index >= 0
  - constraint: status = 'completed' implies completed_at is not null
- `todoist_comments.json` — Comments attached to either a task or a project. Exactly one parent reference is set. (31 rows; fields: ['id', 'todoist_comment_id', 'todoist_task_id', 'todoist_project_id', 'content', 'posted_at', 'attachment', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(todoist_comment_id)
  - constraint: exactly_one_non_null(todoist_task_id, todoist_project_id)
  - constraint: status = 'deleted' implies deleted_at is not null
  - constraint: status != 'deleted' implies deleted_at is null

## Business rules enforced by the tools

- todoist_create_project inserts a todoist_projects row with status='active' and a new unique todoist_project_id (or stores the upstream id if already known) and must reject empty name.
- todoist_get_projects returns projects where status!='deleted' with pagination (limit 1..200, default 50) ordered by order_index then created_at.
- todoist_get_project looks up by todoist_project_id and must return 404-equivalent if status='deleted' or not found.
- todoist_update_project may change name/color/is_favorite/view_style/order_index/status (active<->archived). It must not allow updates when status='deleted'.
- todoist_delete_project transitions project status to 'deleted' and sets deleted_at; it must also soft-delete (status='deleted') all sections and tasks in that project in the same transaction (or enqueue equivalent cascading action).
- todoist_create_section inserts a todoist_sections row with status='active' and must validate referenced todoist_project_id exists and is not deleted.
- todoist_get_sections supports filtering by todoist_project_id; it must return only status!='deleted' sections with pagination.
- todoist_update_section can modify name/order_index and must reject if section status='deleted'.
- todoist_delete_section sets status='deleted' and deleted_at; tasks in that section must have todoist_section_id set to null (or moved) unless the upstream semantics enforce cascade; the backend must ensure no task references a deleted section.
- todoist_create_label inserts todoist_labels with status='active' and must enforce unique(name) among non-deleted labels.
- todoist_get_labels returns only labels with status!='deleted' with pagination.
- todoist_get_label looks up by todoist_label_id and returns not-found if deleted.
- todoist_update_label may change name/color/order_index/is_favorite; it must enforce unique(name) among non-deleted labels.
- todoist_delete_label sets status='deleted' and deleted_at; any task.labels_todoist_ids containing that label must have it removed on next write or via background cleanup, and new writes must reject including deleted label ids.
- todoist_create_task inserts todoist_tasks with status='active'; it must require content and valid todoist_project_id; todoist_section_id must belong to the same project if provided; priority must be 1..4.
- todoist_quick_add_task inserts todoist_tasks with quick_add_raw populated and best-effort parsing result stored in quick_add_parse_result; it must still enforce the same referential constraints as create_task after parsing.
- todoist_get_tasks returns tasks with status in ('active','completed') by default (excluding deleted) and supports filtering by todoist_project_id, todoist_section_id, parent_todoist_task_id, label ids, priority, and due presence/date ranges; results are paginated and stable-sorted by due then order_index then created_at.
- todoist_get_task looks up by todoist_task_id and returns not-found if status='deleted'.
- todoist_update_task may change content/description/priority/due/deadline/labels_todoist_ids/assignee_todoist_id/order_index; it must reject updates when status='deleted' and must validate referenced project/section/parent and labels.
- todoist_delete_task transitions status to 'deleted' with deleted_at; it must also soft-delete all descendant subtasks (where parent_todoist_task_id chains from this task) in the same transaction or queued cascade.
- todoist_complete_task transitions status from 'active' to 'completed' and sets completed_at=now; it must be idempotent (calling on completed task keeps completed status and does not clear completed_at).
- todoist_reopen_task transitions status from 'completed' to 'active' and clears completed_at; it must be idempotent for already-active tasks.
- todoist_search_tasks performs case-insensitive substring match over content (and optionally description) among tasks where status!='deleted'; it must return paginated results.
- todoist_move_task requires exactly one of destination fields (todoist_project_id, todoist_section_id, parent_todoist_task_id). It must update the task and all descendants to the new project/section when moving across projects, ensuring section belongs to project and parent is not deleted.
- todoist_bulk_move_tasks applies the same validation as move_task for each todoist_task_id; it must be atomic per task (fail-fast or return per-task errors) and should cap the number of taskIds processed per call (e.g., <= 200) to protect the system.
- todoist_create_comment inserts todoist_comments with status='active' and must enforce exactly one of todoist_task_id or todoist_project_id is provided and references a non-deleted parent.
- todoist_get_comments supports filtering by todoist_task_id or todoist_project_id with pagination and returns only status!='deleted'.
- todoist_get_comment looks up by todoist_comment_id and returns not-found if status='deleted'.
- todoist_update_comment updates content only and must reject if status='deleted'.
- todoist_delete_comment sets status='deleted' and deleted_at and must be idempotent.