# Todoist Integration — local MCP environment

This backend stores a local mirror of a user's Todoist workspace (projects, sections, tasks, comments, labels) plus collaboration/shared-label metadata needed to serve read APIs quickly and to track lifecycle changes like completion/reopen and deletion. Write tools enqueue changes to Todoist and update the local mirror, while read tools primarily query the mirrored entities and derived indexes (e.g., completion timestamps for productivity stats).

Repository: https://github.com/miottid/todoist-mcp
Homepage: https://smithery.ai/server/@miottid/todoist-mcp

## Datastore

- `todoist_accounts.json` — Represents an authenticated Todoist account/workspace connection used by the integration. Holds the Todoist user identity and credentials metadata needed to sync and make API calls. (12 rows; fields: ['id', 'todoist_user_id', 'email', 'display_name', 'access_token_hash', 'access_token_last4', 'scopes', 'sync_cursor', 'last_synced_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error', 'disabled']
  - constraint: unique(todoist_user_id)
  - constraint: status in ('active','revoked','error','disabled')
  - constraint: json_array_length(scopes) >= 0
- `projects.json` — Todoist projects mirrored locally. Supports CRUD, collaborators listing, and comment attachment at project level. (19 rows; fields: ['id', 'account_id', 'todoist_project_id', 'name', 'color', 'parent_project_id', 'is_favorite', 'view_style', 'inbox_project', 'sort_order', 'status', 'last_todoist_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(account_id, todoist_project_id)
  - constraint: name <> ''
  - constraint: sort_order is null or sort_order >= 0
  - constraint: view_style is null or view_style in ('list','board')
- `sections.json` — Todoist sections within projects. Supports CRUD and listing by project. (34 rows; fields: ['id', 'account_id', 'project_id', 'todoist_section_id', 'name', 'order', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, todoist_section_id)
  - constraint: unique(project_id, name) where status='active'
  - constraint: order is null or order >= 0
  - constraint: name <> ''
- `tasks.json` — Todoist tasks mirrored locally. Supports creation (including quick add), retrieval, update, close/reopen, delete, moving tasks, filtering, and completed-task reporting for date-range and productivity stats. (36 rows; fields: ['id', 'account_id', 'todoist_task_id', 'project_id', 'section_id', 'parent_task_id', 'content', 'description', 'priority', 'labels', 'due_date', 'due_timezone', 'due_lang', 'deadline_date', 'duration_amount', 'duration_unit', 'order', 'created_by_todoist_at', 'completed_at', 'quick_add_text', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: unique(account_id, todoist_task_id)
  - constraint: content <> ''
  - constraint: priority between 1 and 4
  - constraint: duration_amount is null or duration_amount > 0
- `comments.json` — Comments mirrored locally. Comments can attach to either a task or a project. Supports CRUD and listing by task/project. (35 rows; fields: ['id', 'account_id', 'todoist_comment_id', 'project_id', 'task_id', 'content', 'posted_by_todoist_user_id', 'attachment', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, todoist_comment_id)
  - constraint: content <> ''
  - constraint: not (project_id is null and task_id is null)
  - constraint: not (project_id is not null and task_id is not null)
- `labels.json` — Label catalog for the account. Supports retrieving labels, updating/deleting labels, and managing shared labels (get/rename/remove). (29 rows; fields: ['id', 'account_id', 'todoist_label_id', 'name', 'color', 'is_favorite', 'is_shared', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, todoist_label_id) where todoist_label_id is not null
  - constraint: unique(account_id, name) where status='active'
  - constraint: name <> ''
  - constraint: is_shared in (true,false)

## Business rules enforced by the tools

- All reads and writes are scoped to exactly one todoist_accounts row determined by the runtime integration context; tools must not access entities across accounts.
- delete-project, delete-section, delete-task, delete-comment, and delete-label perform soft deletes by setting status='deleted' and updating updated_at; hard delete is not allowed.
- close-task sets tasks.status='completed' and tasks.completed_at=now(); it is invalid to close an already deleted task.
- reopen-task sets tasks.status='active' and tasks.completed_at=NULL; it is invalid to reopen a deleted task.
- move-tasks must update project_id/section_id/parent_task_id for all targeted tasks in a single transaction; if moving to a different project, section_id must be NULL unless a section in that target project is explicitly set.
- get-tasks-completed-by-completion-date filters tasks where status='completed' and completed_at is within the requested inclusive date range; tasks without completed_at must be excluded.
- get-tasks-completed-by-due-date filters tasks where status='completed' and due_date is within the requested inclusive date range (regardless of completed_at), excluding tasks with NULL due_date.
- get-productivity-stats is computed only from tasks with status='completed' and non-NULL completed_at; counts/groupings must be reproducible for a given time range and timezone assumptions.
- get-tasks-by-filter must be implemented as a server-side translation to predicates over tasks fields (content, project_id, labels, priority, created_by_todoist_at, due_date, status) and may fall back to Todoist API if the filter expression cannot be safely parsed; fallback must update last_todoist_synced_at for touched entities when results are merged.
- add-comment requires exactly one of task_id or project_id; attempts to set both must be rejected.
- get-project-collaborators is served by calling Todoist and may be cached out-of-band; if collaborators are cached, they must be scoped to projects.todoist_project_id and account_id (no cross-project leakage).
- rename-shared-label and remove-shared-label apply only to labels where is_shared=true and status='active'; removing a shared label sets status='deleted' rather than deleting tasks.labels entries (historical task labels remain as recorded).
- add-label attaches a label to a task by inserting/updating tasks.labels array and ensuring a corresponding labels row exists (create if missing with is_shared=false unless known shared); label names are case-insensitive unique per account (normalize to a canonical form).
- FK integrity: sections.project_id must reference a non-deleted project; tasks.project_id must reference a non-deleted project when non-NULL; tasks.section_id must reference a non-deleted section when non-NULL; comments.task_id/comments.project_id must reference non-deleted entities when present.