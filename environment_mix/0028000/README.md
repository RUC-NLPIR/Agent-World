# TickTick API Server — local MCP environment

This backend stores TickTick-like task management data: users connect via API tokens, organize work into projects, and manage tasks within those projects. Core workflows include listing a user’s projects, creating/updating/deleting projects, and creating/updating/completing/deleting tasks; projects can also be fetched with their associated tasks and kanban-style columns.

Repository: https://github.com/alexarevalo9/ticktick-mcp-server
Homepage: https://smithery.ai/server/@alexarevalo9/ticktick-mcp-server

## Datastore

- `users.json` — End-user accounts that own projects and tasks; included to support per-user scoping for all read/write operations. (12 rows; fields: ['id', 'email', 'display_name', 'timezone', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(email) where email is not null
  - constraint: timezone must be a valid IANA timezone string
  - constraint: status != 'deleted' required for authentication/authorization
- `api_tokens.json` — Personal access tokens / OAuth access tokens used by the MCP server to authenticate calls on behalf of a user. (12 rows; fields: ['id', 'user_id', 'provider', 'access_token', 'refresh_token', 'scopes', 'expires_at', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: fk(user_id) references users(id) on delete cascade
  - constraint: expires_at must be >= created_at when not null
  - constraint: unique(user_id, provider, access_token) (stored as token fingerprint) to prevent duplicates
- `projects.json` — Projects (lists) that group tasks; may be configured as list or kanban with columns. (18 rows; fields: ['id', 'user_id', 'name', 'color', 'view_mode', 'sort_order', 'is_archived', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: fk(user_id) references users(id) on delete cascade
  - constraint: unique(user_id, name) where status != 'deleted'
  - constraint: sort_order >= 0
  - constraint: is_archived = true implies status = 'archived' OR status='deleted'
- `project_columns.json` — Kanban columns for a project; used when fetching 'project with data' and when tasks are placed into columns. (16 rows; fields: ['id', 'project_id', 'name', 'sort_order', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(project_id) references projects(id) on delete cascade
  - constraint: unique(project_id, name) where status='active'
  - constraint: unique(project_id, sort_order) where status='active'
  - constraint: sort_order >= 0
- `tasks.json` — Tasks belonging to projects; supports create/update/complete/delete and lookup by project + task id. (36 rows; fields: ['id', 'project_id', 'user_id', 'column_id', 'title', 'content', 'priority', 'due_at', 'start_at', 'completed_at', 'status', 'is_all_day', 'sort_order', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: fk(project_id) references projects(id) on delete cascade
  - constraint: fk(user_id) references users(id) on delete cascade
  - constraint: fk(column_id) references project_columns(id) on delete set null
  - constraint: user_id must equal (select user_id from projects where projects.id = project_id)

## Business rules enforced by the tools

- All tools operate in the context of an authenticated user resolved from api_tokens where status='active' and (expires_at is null or expires_at > now()).
- get_user_projects returns projects for the authenticated user where status in ('active','archived') ordered by sort_order asc, created_at asc.
- get_project_by_id reads a single project by projects.id and enforces projects.user_id = current_user.id and projects.status != 'deleted'.
- get_project_with_data returns the project plus (a) all non-deleted tasks in that project and (b) all active project_columns for that project; tasks are returned with their column_id placements.
- create_project inserts into projects with user_id=current_user.id, status='active', is_archived=false, view_mode default 'list' if not provided by the service layer; name must be non-empty and unique per user among non-deleted projects.
- update_project may modify name/color/view_mode/sort_order/is_archived; setting is_archived=true forces status='archived', setting is_archived=false forces status='active' unless status already 'deleted'.
- delete_project sets projects.status='deleted' and deleted_at=now(); all child project_columns are set to status='deleted'; all child tasks are set to status='deleted' and deleted_at=now() (or via FK cascade + trigger).
- get_task_by_ids fetches a task by (project_id, task_id) ensuring the project belongs to the current user and both project and task are not status='deleted'.
- create_task inserts into tasks with project_id validated to belong to current_user; status='active'; completed_at null; if project.view_mode='kanban' and column_id is provided it must reference an active column in that same project.
- update_task updates mutable fields (title/content/priority/due_at/start_at/is_all_day/sort_order/column_id) and may toggle status between 'active' and 'completed' subject to lifecycle transitions; cannot directly update a task with status='deleted'.
- complete_task sets tasks.status='completed' and completed_at=now(); repeated completion is idempotent (no-op if already completed).
- delete_task sets tasks.status='deleted' and deleted_at=now(); operation is idempotent (no-op if already deleted).
- Integrity constraint: it is forbidden to have tasks.user_id differ from projects.user_id for the referenced project_id; enforced by a database constraint or trigger.
- Quota-like safety: a single user may have at most 500 active projects and 200000 non-deleted tasks (enforced at write time by the service layer).