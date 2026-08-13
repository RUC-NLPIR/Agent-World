# Todoist-mcp-server-extended — local MCP environment

This backend mirrors a Todoist workspace for MCP-driven automation: tasks live inside projects and optional sections, and tasks can be tagged with both personal and shared labels. The main workflows are CRUD on tasks/projects/sections/labels, completing tasks, and managing task↔label associations (including renaming/removing shared labels across tasks).

Repository: https://github.com/Chrusic/todoist-mcp-server-extended
Homepage: https://smithery.ai/server/@Chrusic/todoist-mcp-server-extended

## Datastore

- `projects.json` — Todoist projects, including nested hierarchies. Used by get/create/update project tools and as the parent container for sections and tasks. (17 rows; fields: ['id', 'todoist_project_id', 'parent_project_id', 'name', 'color', 'is_favorite', 'view_style', 'order_index', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(todoist_project_id)
  - constraint: parent_project_id references projects.id on delete set null
  - constraint: order_index >= 0
  - constraint: view_style in ('list','board','calendar','unknown')
- `sections.json` — Sections within Todoist projects. Used by get/create project section tools and for task placement. (18 rows; fields: ['id', 'todoist_section_id', 'project_id', 'name', 'order_index', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(todoist_section_id)
  - constraint: project_id references projects.id on delete cascade
  - constraint: unique(project_id, name) where status = 'active'
  - constraint: order_index >= 0
- `tasks.json` — Todoist tasks (items), including completion and scheduling metadata. Supports create/get/update/delete/complete task tools and label updates via the task_labels join. (18 rows; fields: ['id', 'todoist_task_id', 'project_id', 'section_id', 'parent_task_id', 'content', 'description', 'priority', 'due', 'deadline', 'duration', 'order_index', 'is_recurring', 'completed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: unique(todoist_task_id)
  - constraint: project_id references projects.id on delete restrict
  - constraint: section_id references sections.id on delete set null
  - constraint: parent_task_id references tasks.id on delete set null
- `labels.json` — Labels available to tasks. Contains both personal and shared labels; shared labels can be renamed or removed from tasks. (18 rows; fields: ['id', 'todoist_label_id', 'name', 'color', 'is_favorite', 'label_type', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(todoist_label_id)
  - constraint: unique(label_type, name) where status = 'active'
  - constraint: label_type in ('personal','shared')
- `task_labels.json` — Many-to-many join between tasks and labels. Supports updating task labels, removing shared labels from tasks, and reading tasks with label metadata. (18 rows; fields: ['id', 'task_id', 'label_id', 'source', 'created_at', 'updated_at'])
  - lifecycle `source`: ['user', 'automation', 'import', 'sync']
  - constraint: task_id references tasks.id on delete cascade
  - constraint: label_id references labels.id on delete cascade
  - constraint: unique(task_id, label_id)
  - constraint: source in ('user','automation','import','sync')

## Business rules enforced by the tools

- todoist_create_task inserts a row into tasks (status='active', completed_at=null) and optionally inserts rows into task_labels for any provided label identifiers; project_id must reference an active project; section_id (if provided) must reference an active section belonging to the same project.
- todoist_get_tasks reads from tasks with optional filtering by project_id, section_id, status, due/deadline presence/range, priority, parent_task_id, and label membership via task_labels; batch retrieval is implemented as an IN filter on todoist_task_id or local id.
- todoist_update_task updates mutable task fields (content, description, priority, due, deadline, duration, project_id, section_id, parent_task_id, order_index) but must reject updates when status='deleted'; moving a task to a new section must satisfy the section→project consistency rule.
- todoist_delete_task sets tasks.status='deleted' (soft delete) and deletes task_labels by FK cascade; deleting is idempotent (re-deleting a deleted task is a no-op).
- todoist_complete_task transitions tasks.status from 'active' to 'completed' and sets completed_at=now; completing an already completed task is a no-op; completing a deleted task is rejected.
- todoist_get_projects reads from projects with optional filtering by status and parent_project_id; hierarchy information is derived by self-join on parent_project_id.
- todoist_create_project inserts one or more projects; if parent_project_id is provided it must reference an existing active project; project.todoist_project_id must be unique.
- todoist_update_project updates mutable fields (name, color, is_favorite, view_style, order_index, status with allowed transitions); setting status='deleted' must also soft-delete dependent sections (set status='deleted') and soft-delete dependent tasks (set status='deleted') in the same transaction or via background job.
- todoist_get_project_sections reads sections filtered by one or more project_id values; only sections with status='active' are returned unless explicitly requesting deleted (internal/admin behavior).
- todoist_create_project_section inserts one or more sections for a given project; (project_id,name) must be unique among active sections.
- todoist_get_personal_labels reads labels where label_type='personal' and status='active'.
- todoist_create_personal_label inserts one or more labels with label_type='personal' and status='active'; (label_type,name) must be unique among active labels.
- todoist_get_personal_label reads a single labels row by todoist_label_id or local id, enforcing label_type='personal'.
- todoist_update_personal_label updates labels where label_type='personal' and status='active'; renaming must preserve uniqueness within personal labels.
- todoist_delete_personal_label sets labels.status='deleted' for label_type='personal' and removes associations by deleting related task_labels rows (FK cascade).
- todoist_get_shared_labels reads labels where label_type='shared' and status='active'.
- todoist_rename_shared_labels updates labels.name for label_type='shared' and status='active' in batch; new names must not collide with existing active shared label names.
- todoist_remove_shared_labels removes shared labels from tasks by deleting rows in task_labels where label_id references labels rows with label_type='shared' and matching names/ids.
- todoist_update_task_labels replaces or patches a task's labels by inserting/deleting rows in task_labels; duplicate associations are prevented by unique(task_id,label_id); attempts to attach deleted labels or attach labels to deleted tasks are rejected.
- All write tools must update updated_at timestamps on affected rows; reads should exclude status='deleted' by default unless the tool explicitly requests deleted entities (not exposed on this surface).