# Linear Issue and Project Management Server — local MCP environment

This backend stores Linear-like workspaces containing teams, projects, and issues. Core workflows include listing workspace metadata, creating/updating issues, retrieving issue details, listing/filtering issues/projects/teams, returning team workflow states, and searching issues by text within a workspace/team context.

Repository: https://github.com/crafted-app/linear-mcp
Homepage: https://smithery.ai/server/@crafted-app/linear-mcp

## Datastore

- `workspaces.json` — Top-level tenant/container. A workspace owns teams, projects and issues. (12 rows; fields: ['id', 'name', 'slug', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name != ''
  - constraint: status in ('active','suspended','deleted')
- `teams.json` — Teams inside a workspace. Teams define the workflow states (issue statuses) that issues can be in. (12 rows; fields: ['id', 'workspace_id', 'key', 'name', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, key)
  - constraint: unique(workspace_id, name)
  - constraint: key matches '^[A-Z][A-Z0-9]{1,9}$'
- `workflow_states.json` — Team-scoped workflow states (statuses) for issues; returned by get_issue_status and used by issues.state_id. (34 rows; fields: ['id', 'team_id', 'name', 'description', 'position', 'type', 'is_default', 'is_resolved', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: fk(team_id) references teams(id) on delete restrict
  - constraint: unique(team_id, name)
  - constraint: unique(team_id, position)
  - constraint: position >= 0
- `projects.json` — Projects within a workspace; issues can optionally belong to a project. (20 rows; fields: ['id', 'workspace_id', 'name', 'description', 'start_date', 'target_date', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['planned', 'started', 'paused', 'completed', 'canceled', 'archived']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: name != ''
  - constraint: target_date is null or start_date is null or target_date >= start_date
- `issues.json` — Work items tracked by teams; can be searched, listed, created, updated, and fetched in detail. (35 rows; fields: ['id', 'workspace_id', 'team_id', 'project_id', 'state_id', 'identifier', 'number', 'title', 'description', 'priority', 'estimate', 'due_date', 'labels', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(team_id) references teams(id) on delete restrict
  - constraint: fk(project_id) references projects(id) on delete set null
  - constraint: fk(state_id) references workflow_states(id) on delete restrict

## Business rules enforced by the tools

- list_workspaces returns all workspaces where status != 'deleted' (or only those visible to the calling API token; access control is out of scope but must filter by workspace).
- list_teams returns teams for a given workspace context and must exclude teams with status='archived' unless an explicit include_archived flag exists at implementation time.
- get_issue_status returns workflow_states filtered by team_id, ordered by position ascending, and only where status='active' by default.
- list_projects returns projects filtered by workspace_id and excludes status='archived' by default; ordering is by updated_at desc then created_at desc.
- create_issue must allocate the next issues.number per team_id atomically (no duplicates), set identifier = concat(teams.key, '-', number), and set state_id to the team's single workflow_states.is_default=true state unless a specific state_id is provided by the implementation.
- create_issue must reject if team.status != 'active' or workspace.status != 'active'.
- update_issue may modify title, description, priority, estimate, due_date, labels, project_id, and state_id; it must reject any update that violates FK constraints or cross-workspace/team consistency (project must belong to same workspace, state must belong to same team).
- get_issue fetches a single issue by id and must return 404 if status='deleted' unless a privileged flag exists at implementation time.
- list_issues supports filtering at minimum by workspace_id, team_id, project_id, state_id, status, priority range, and updated_at window as implemented; all filters map directly to issues fields or referenced ids.
- search_issues performs full-text search over issues.title and issues.description with optional filters (workspace_id/team_id/project_id/state_id/status); results are restricted to status='active' by default and ranked primarily by text relevance then updated_at desc.
- Deleting is logical: issues.status can transition from 'active' to 'deleted' only; deleted issues cannot be updated except possibly to restore (not supported by this tool surface).
- A team must always have exactly one active default workflow state (workflow_states.is_default=true and status='active'); attempts to deprecate the default state must first move the default flag to another active state.
- All timestamps are server-generated; updated_at must change on every mutation to the row.