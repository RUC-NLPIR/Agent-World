# Todoist Integration Server — local MCP environment

This backend stores a local, API-driven mirror of a user's Todoist domain objects (projects, sections, tasks, labels, comments) plus minimal collaboration metadata, to support CRUD, completion/reopen workflows, and filter-based task search. The integration server primarily brokers requests to Todoist, but a production backend persists normalized entities, enforces referential integrity, and tracks lifecycle/status and audit history needed for idempotent operations and analytics-like endpoints (completed-task queries, productivity stats).

Repository: https://github.com/Doist/todoist-mcp
Homepage: https://smithery.ai/server/@Doist/todoist-mcp

## Datastore

- `projects.json` — Todoist projects and their collaborator lists. Supports project CRUD and listing collaborators for a project. (29 rows; fields: ['id', 'todoist_project_id', 'name', 'color', 'parent_project_id', 'is_favorite', 'view_style', 'collaborators', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(todoist_project_id)
  - constraint: name <> ''
  - constraint: parent_project_id IS NULL OR parent_project_id <> id
  - constraint: status IN ('active','archived','deleted')
- `sections.json` — Sections within projects. Supports section CRUD and listing sections by project. (32 rows; fields: ['id', 'todoist_section_id', 'project_id', 'name', 'order', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(todoist_section_id)
  - constraint: unique(project_id, name) WHERE status <> 'deleted'
  - constraint: name <> ''
  - constraint: order IS NULL OR order >= 0
- `tasks.json` — Todoist tasks including completion lifecycle, scheduling fields, and move operations. Supports task CRUD, quick-add normalization output, completion queries by completion/due date range, and productivity stats rollups. (35 rows; fields: ['id', 'todoist_task_id', 'project_id', 'section_id', 'parent_task_id', 'content', 'description', 'priority', 'labels', 'due_date', 'due_date_text', 'due_timezone', 'deadline_date', 'deadline_lang', 'duration_amount', 'duration_unit', 'created_by_quick_add', 'quick_add_raw_text', 'filter_cache_tokens', 'status', 'completed_at', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: unique(todoist_task_id)
  - constraint: priority BETWEEN 1 AND 4
  - constraint: duration_amount IS NULL OR duration_amount > 0
  - constraint: duration_unit IS NULL OR duration_unit IN ('minute','day')
- `labels.json` — Todoist personal and shared labels. Supports label CRUD plus shared-label operations (list/rename/remove). (30 rows; fields: ['id', 'todoist_label_id', 'name', 'color', 'is_favorite', 'is_shared', 'shared_origin', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(todoist_label_id) WHERE todoist_label_id IS NOT NULL
  - constraint: unique(lower(name)) WHERE status = 'active'
  - constraint: name <> ''
  - constraint: shared_origin IS NULL OR shared_origin IN ('name','id','unknown')
- `comments.json` — Comments attached to either a task or a project. Supports comment CRUD and list-by-task/project endpoints. (32 rows; fields: ['id', 'todoist_comment_id', 'target_type', 'task_id', 'project_id', 'content', 'attachment', 'posted_by', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(todoist_comment_id)
  - constraint: content <> ''
  - constraint: target_type IN ('task','project')
  - constraint: ((target_type='task' AND task_id IS NOT NULL AND project_id IS NULL) OR (target_type='project' AND project_id IS NOT NULL AND task_id IS NULL))

## Business rules enforced by the tools

- All mutating tools (add/update/delete/close/reopen/move/rename/remove) MUST be idempotent by upstream Todoist id: if a row with the given todoist_*_id exists, update it instead of inserting a duplicate.
- delete-project, delete-section, delete-task, delete-comment, delete-label MUST soft-delete by setting status='deleted'/'removed' and deleted_at, and MUST NOT physically remove rows.
- close-task MUST transition tasks.status from 'active' to 'completed' and MUST set completed_at to the operation time; it MUST NOT complete a task already in status='deleted'.
- reopen-task MUST transition tasks.status from 'completed' to 'active' and MUST clear completed_at; it MUST NOT reopen a task in status='deleted'.
- move-tasks MUST update project_id/section_id/parent_task_id for all specified tasks atomically; section_id MUST belong to the same project_id after move, otherwise the move is rejected.
- get-tasks-completed-by-completion-date MUST return tasks where status='completed' and completed_at is within the requested date range (inclusive).
- get-tasks-completed-by-due-date MUST return tasks where status='completed' and due_date is within the requested date range (inclusive), regardless of completed_at.
- get-productivity-stats MUST compute counts of completed tasks grouped by day/week (implementation-defined) using completed_at and MUST exclude deleted tasks.
- get-tasks-by-filter MUST only return tasks with status='active' (unless filter explicitly requests otherwise) and MUST use filter_cache_tokens plus direct fields (priority, labels, project_id, due_date) to evaluate common Todoist filters; unsupported filter constructs MUST return a validation error rather than silently mis-filtering.
- add-comment MUST create a comment with exactly one target: either task_id or project_id; it MUST reject requests specifying both or neither.
- add-label attaches a label to a task by adding the label's internal id to tasks.labels; delete-label/remove-shared-label MUST also remove that label id from all tasks.labels in the same transaction.
- rename-shared-label MUST only apply to labels where is_shared=true and status='active', and MUST maintain uniqueness of lower(name) among active labels.