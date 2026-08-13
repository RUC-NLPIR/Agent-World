# Linear MCP Server — local MCP environment

This backend stores a Linear-like workspace with teams, projects, and issues, supporting creation, updates, listing, and retrieval. It also supports full-text search over issues and basic API auditing of requests so the MCP tools can list/search/get and mutate issues reliably.

Repository: https://github.com/tiovikram/linear-mcp
Homepage: https://smithery.ai/server/@tiovikram/linear-mcp

## Datastore

- `workspaces.json` — A Linear workspace (organization) that owns teams, projects, and issues. Included to scope data and enforce uniqueness constraints (e.g., team keys, issue identifiers). (12 rows; fields: ['id', 'name', 'slug', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name <> ''
  - constraint: slug <> ''
- `teams.json` — Teams within a workspace. Issues belong to a team and have a team-scoped human identifier like ABC-123 derived from the team key and issue number. (12 rows; fields: ['id', 'workspace_id', 'name', 'key', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, key)
  - constraint: unique(workspace_id, name)
  - constraint: key ~ '^[A-Z][A-Z0-9]{1,9}$'
- `projects.json` — Projects in a workspace. Issues may optionally be associated with a project; projects are returned by list_projects. (20 rows; fields: ['id', 'workspace_id', 'name', 'description', 'start_date', 'target_date', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['planned', 'started', 'paused', 'completed', 'canceled', 'archived']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: name <> ''
- `issues.json` — Issues (tickets). Supports create_issue, update_issue, list_issues, get_issue, and search_issues. Includes team-scoped sequence numbers to generate human-readable identifiers like TEAM-123. (35 rows; fields: ['id', 'workspace_id', 'team_id', 'project_id', 'number', 'identifier', 'title', 'description', 'priority', 'status', 'labels', 'due_date', 'created_at', 'updated_at', 'completed_at'])
  - lifecycle `status`: ['triage', 'backlog', 'started', 'completed', 'canceled']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(team_id) references teams(id) on delete restrict
  - constraint: fk(project_id) references projects(id) on delete set null
  - constraint: unique(team_id, number)
- `api_requests.json` — Audit and operational telemetry for tool calls (create/update/list/search/get). Enables debugging, rate limiting, and basic usage analytics even when tool parameters are empty in the published schema. (37 rows; fields: ['id', 'workspace_id', 'tool_name', 'status', 'request_payload', 'response_summary', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'succeeded', 'failed']
  - constraint: tool_name in ('create_issue','list_issues','update_issue','list_teams','list_projects','search_issues','get_issue')
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: status <> ''

## Business rules enforced by the tools

- All reads and writes are scoped to a single workspace derived from the caller's auth context; cross-workspace access is forbidden.
- create_issue must create an issues row with team_id required, set number to (max(number)+1) for that team in a transaction, and set identifier = teams.key || '-' || number; it must fail if the team is not active.
- update_issue must only update mutable fields on issues (title, description, priority, status, labels, project_id, due_date); it must reject updates to team_id, number, identifier, and workspace_id.
- When an issue status transitions to completed, completed_at must be set to now; when transitioning away from completed, completed_at must be cleared.
- get_issue must retrieve by issues.id and return all issue fields; if not found in the caller workspace, return not found.
- list_issues must return issues filtered at minimum by workspace_id; optional filtering (team_id, project_id, status, priority, label membership, created_at range) is implemented via fields on issues even though the published tool schema shows no parameters.
- search_issues performs full-text search over issues.title and issues.description (and optionally identifier) within the workspace; results are ranked by text relevance and recency, and must not return issues from archived teams unless explicitly configured server-side.
- list_teams returns all teams in the workspace where status in ('active','archived'), ordered by name; list_projects returns all projects in the workspace ordered by updated_at desc.
- Any tool invocation must write an api_requests row with tool_name, request_payload, and final status; failed requests must set error_message.
- FK integrity: issues.workspace_id must match teams.workspace_id for its team_id, and if project_id is set, issues.workspace_id must match projects.workspace_id; otherwise the write is rejected.