# Clockify Time Entry Manager — local MCP environment

This backend stores Clockify-linked identities (current user), the workspaces they can access, projects inside those workspaces, and time entries created by the integration. Primary workflows are: discover current user, list accessible workspaces, list projects for a workspace, and create a time entry associated to a user/workspace and optionally a project.

Repository: https://github.com/https-eduardo/clockify-mcp-server
Homepage: https://smithery.ai/server/@https-eduardo/clockify-mcp-server

## Datastore

- `clockify_users.json` — Clockify user identities resolved via the connected API token. Used by get-current-user and as the actor/owner for time entries. (12 rows; fields: ['id', 'clockify_user_id', 'display_name', 'email', 'timezone', 'status', 'created_at', 'updated_at', 'last_synced_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(clockify_user_id)
  - constraint: display_name <> ''
  - constraint: status in ('active','revoked')
- `workspaces.json` — Clockify workspaces accessible to the current user. Used by get-workspaces and as the container for projects and time entries. (12 rows; fields: ['id', 'clockify_workspace_id', 'name', 'status', 'created_at', 'updated_at', 'last_synced_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(clockify_workspace_id)
  - constraint: name <> ''
  - constraint: status in ('active','archived')
- `workspace_memberships.json` — Join table capturing which Clockify users can access which workspaces (as discovered via get-workspaces). Enables per-user filtering of workspaces and validates time entry creation permissions. (12 rows; fields: ['id', 'user_id', 'workspace_id', 'role', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(user_id, workspace_id)
  - constraint: role in ('owner','admin','member','viewer')
  - constraint: status in ('active','inactive')
  - constraint: fk(user_id) references clockify_users(id) on delete cascade
- `projects.json` — Projects within a workspace. Used by get-projects and optionally associated to time entries. (27 rows; fields: ['id', 'workspace_id', 'clockify_project_id', 'name', 'color', 'billable_default', 'status', 'created_at', 'updated_at', 'last_synced_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(workspace_id, clockify_project_id)
  - constraint: name <> ''
  - constraint: status in ('active','archived')
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
- `time_entries.json` — Time entries created via the integration and/or mirrored from Clockify. Supports create-time-entry and provides an audit trail for what was created, when, and with which upstream ids. (33 rows; fields: ['id', 'clockify_time_entry_id', 'workspace_id', 'user_id', 'project_id', 'description', 'start_time', 'end_time', 'billable', 'tags', 'status', 'error_message', 'created_via', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'created', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(user_id) references clockify_users(id) on delete restrict
  - constraint: fk(project_id) references projects(id) on delete set null
  - constraint: if project_id is not null then projects.workspace_id must equal time_entries.workspace_id

## Business rules enforced by the tools

- get-current-user returns the single clockify_users row with status='active' for the configured API token context; if none exists, the implementation must create/sync it from Clockify and persist it.
- get-workspaces returns workspaces joined through workspace_memberships where workspace_memberships.user_id is the active user and workspace_memberships.status='active' and workspaces.status='active'.
- get-projects returns projects for a workspace that the active user has an active workspace_memberships row for; only projects.status='active' are returned.
- create-time-entry must only create an entry for a workspace where the active user has workspace_memberships.status='active'.
- If create-time-entry associates a project, that project must belong to the same workspace as the time entry (projects.workspace_id = time_entries.workspace_id).
- A 'running' time entry is represented by end_time = null; if end_time is provided then start_time must also be provided and end_time >= start_time.
- When create-time-entry is invoked, a time_entries row is first inserted with status='pending'; upon upstream success it is updated to status='created' and clockify_time_entry_id is set; upon upstream failure it is updated to status='failed' with error_message populated.
- Only valid status transitions defined in each collection's lifecycle.transitions may be applied by mutating operations.
- Uniqueness constraints must be enforced: clockify_users.clockify_user_id, workspaces.clockify_workspace_id, projects(workspace_id, clockify_project_id), and time_entries.clockify_time_entry_id (when not null).