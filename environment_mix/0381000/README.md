# Todoist Task and Project Manager — local MCP environment

This backend stores Todoist-like projects, sections, tasks, comments, and labels for a single account/workspace, including collaboration and label sharing. Main workflows include CRUD over projects/sections/tasks/comments/labels, task state changes (complete/reopen), project archiving, and managing shared labels and project collaborators.

Repository: https://github.com/stevengonsalvez/todoist-mcp
Homepage: https://smithery.ai/server/@stevengonsalvez/todoist-mcp

## Datastore

- `projects.json` — Projects are top-level containers for tasks and sections, can be archived/unarchived/deleted, and can have collaborators. (18 rows; fields: ['id', 'name', 'color', 'parent_project_id', 'order_index', 'is_favorite', 'is_inbox', 'view_style', 'status', 'archived_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: required(name, order_index, is_favorite, is_inbox, view_style, status, created_at, updated_at)
  - constraint: unique(is_inbox) WHERE is_inbox = true AND status != 'deleted'
  - constraint: unique(parent_project_id, order_index) WHERE status != 'deleted'
  - constraint: order_index >= 0
- `sections.json` — Sections partition a project into named lists. Tasks may belong to a section within a project. (18 rows; fields: ['id', 'project_id', 'name', 'order_index', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: required(project_id, name, order_index, status, created_at, updated_at)
  - constraint: fk(project_id) references projects(id) ON UPDATE RESTRICT ON DELETE RESTRICT
  - constraint: unique(project_id, order_index) WHERE status != 'deleted'
  - constraint: order_index >= 0
- `tasks.json` — Tasks are actionable items that can be completed/reopened, optionally assigned to a project/section, and can carry multiple labels. Comments attach to tasks. (19 rows; fields: ['id', 'content', 'description', 'project_id', 'section_id', 'parent_task_id', 'priority', 'due_at', 'due_date', 'timezone', 'order_index', 'is_recurring', 'completed_at', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: required(content, priority, order_index, is_recurring, status, created_at, updated_at)
  - constraint: priority IN (1,2,3,4)
  - constraint: order_index >= 0
  - constraint: fk(project_id) references projects(id) ON UPDATE RESTRICT ON DELETE RESTRICT
- `comments.json` — Comments are user-authored notes attached to a task or a project. (18 rows; fields: ['id', 'task_id', 'project_id', 'content', 'attachment', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: required(content, status, created_at, updated_at)
  - constraint: fk(task_id) references tasks(id) ON UPDATE RESTRICT ON DELETE RESTRICT
  - constraint: fk(project_id) references projects(id) ON UPDATE RESTRICT ON DELETE RESTRICT
  - constraint: exactly_one_of(task_id, project_id) must be non-null
- `labels.json` — Labels (and label sharing) plus task-to-label assignment. Includes shared label concepts to support getSharedLabels/renameSharedLabel/removeSharedLabel. (18 rows; fields: ['id', 'name', 'color', 'order_index', 'is_favorite', 'status', 'deleted_at', 'created_at', 'updated_at', 'task_labels', 'shared_labels', 'project_collaborators'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: required(name, order_index, is_favorite, status, created_at, updated_at)
  - constraint: unique(lower(name)) WHERE status != 'deleted'
  - constraint: order_index >= 0
  - constraint: deleted_at IS NOT NULL IFF status = 'deleted'

## Business rules enforced by the tools

- listTasks returns tasks where status != 'deleted'; may include completed unless the client filters (not present in tool surface).
- getTask requires an existing tasks.id and returns 404 if status='deleted'.
- createTask must create a tasks row with status='active' and completed_at=NULL; if section_id is provided it must belong to the same project_id.
- updateTask may update mutable fields (content, description, project_id, section_id, due_at/due_date/timezone, priority, order_index, parent_task_id) but must not directly set status to 'completed' or 'active'; completeTask/reopenTask are the supported state transitions.
- completeTask transitions tasks.status from 'active' to 'completed' and sets completed_at=now(); it is idempotent if already completed.
- reopenTask transitions tasks.status from 'completed' to 'active' and sets completed_at=NULL; it is idempotent if already active.
- deleteTask transitions tasks.status to 'deleted' and sets deleted_at=now(); subsequent reads via getTask must behave as not found.
- listProjects returns projects where status != 'deleted'.
- archiveProject transitions projects.status from 'active' to 'archived' and sets archived_at=now(); unarchiveProject transitions 'archived' to 'active' and clears archived_at.
- deleteProject transitions projects.status to 'deleted' and sets deleted_at=now(); all contained sections/tasks/comments become inaccessible; referential integrity is enforced via soft-delete rules or cascades on hard-delete jobs.
- getProjectCollaborators reads active collaborator mappings for the given project_id from project_collaborators.
- Sections are always owned by a project; deleting a section marks it deleted and tasks may retain section_id historically but should be treated as unsectioned in reads if the section is deleted (implementation choice).
- listComments returns comments where status != 'deleted' for a given task_id or project_id scope (scope selection is enforced by exactly_one_of(task_id, project_id)).
- Labels are unique case-insensitively among non-deleted labels; deleteLabel marks label deleted and removes/ignores active task_labels associations.
- getSharedLabels returns shared_labels entries with status='active'.
- renameSharedLabel updates shared_labels.shared_name for a given shared label mapping, enforcing uniqueness per shared_with.
- removeSharedLabel transitions shared_labels.status to 'removed' (or deletes it) and it must no longer appear in getSharedLabels.