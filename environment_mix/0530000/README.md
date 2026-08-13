# Linear MCP Server — local MCP environment

This backend stores a local, queryable projection of a Linear workspace (org, users, teams, workflow states, labels, projects, cycles, issues, comments and relationships) plus audit/history needed to serve read APIs and support mutations. Core workflows include listing/searching issues, creating/updating issues and projects, attaching issues to projects/cycles/labels, managing assignments/subscriptions/relations, and recording an immutable issue change history.

Repository: https://github.com/emmett-deen/Linear-MCP-Server
Homepage: https://smithery.ai/server/@emmett-deen/linear-mcp-server

## Datastore

- `linear_org.json` — Organization-level data for the connected Linear workspace plus the current viewer context used by tools like getViewer/getOrganization/getUsers/getTeams/getLabels/getProjects/getCycles. (12 rows; fields: ['id', 'linear_org_id', 'name', 'url_key', 'status', 'viewer_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(linear_org_id)
  - constraint: viewer_user_id references linear_users.id (nullable)
  - constraint: status in ('active','suspended','deleted')
- `linear_users.json` — Users in the organization, including the current viewer. Serves linear_getUsers and supports assignment/subscription operations. (31 rows; fields: ['id', 'org_id', 'linear_user_id', 'display_name', 'email', 'is_active', 'is_admin', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(org_id, linear_user_id)
  - constraint: org_id references linear_org.id
  - constraint: email unique per org when not null: unique(org_id, email) where email is not null
- `linear_workspaces.json` — Team, workflow state, label, project, cycle and their join tables. Serves getTeams/getWorkflowStates/getLabels/getProjects/createProject/updateProject/addIssueToProject/getProjectIssues/getCycles/getActiveCycle/addIssueToCycle. (12 rows; fields: ['id', 'org_id', 'teams', 'workflow_states', 'labels', 'projects', 'project_issues', 'cycles', 'cycle_issues', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: teams: unique(org_id, linear_team_id), unique(org_id, key)
  - constraint: workflow_states: unique(team_id, linear_workflow_state_id), position >= 0
  - constraint: labels: unique(org_id, linear_label_id), unique(org_id, name)
  - constraint: projects: unique(org_id, linear_project_id), unique(org_id, name)
- `linear_issues.json` — Issues plus labels/subscriptions/subtasks/relations and immutable history. Serves getIssues/getIssueById/searchIssues/createIssue/updateIssue/addIssueLabel/removeIssueLabel/assignIssue/subscribeToIssue/convertIssueToSubtask/createIssueRelation/archiveIssue/setIssuePriority/transferIssue/duplicateIssue/getIssueHistory. (32 rows; fields: ['id', 'org_id', 'linear_issue_id', 'identifier', 'team_id', 'title', 'description', 'state_id', 'priority', 'estimate', 'assignee_user_id', 'creator_user_id', 'parent_issue_id', 'due_date', 'status', 'archived_at', 'created_at', 'updated_at', 'issue_labels', 'issue_subscriptions', 'issue_relations', 'issue_history'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(org_id, linear_issue_id)
  - constraint: unique(org_id, identifier)
  - constraint: priority in (0,1,2,3,4)
  - constraint: estimate is null or estimate >= 0
- `linear_comments.json` — Comments on issues. Serves createComment and getComments; also referenced by issue history events. (31 rows; fields: ['id', 'org_id', 'linear_comment_id', 'issue_id', 'author_user_id', 'body', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'edited', 'deleted']
  - constraint: unique(org_id, linear_comment_id)
  - constraint: body length between 1 and 20000 characters
  - constraint: issue_id references linear_issues.id

## Business rules enforced by the tools

- All reads (getViewer/getOrganization/getUsers/getTeams/getWorkflowStates/getLabels/getProjects/getCycles/getIssues/getComments) must scope by a single active linear_org row; if linear_org.status != 'active', tools must fail with an authorization/connection error.
- linear_getViewer returns the user referenced by linear_org.viewer_user_id; if null, the backend must resolve/create the viewer user from upstream and set viewer_user_id.
- linear_getIssueById must accept either (a) linear_issue_id or (b) identifier; identifier must be unique per org and match the team key pattern '^[A-Z][A-Z0-9]*-[0-9]+$'.
- linear_searchIssues filters over linear_issues fields and joins: team_id, state_id, assignee_user_id, priority, status, project membership (project_issues), cycle membership (cycle_issues), label membership (issue_labels), and full-text match over title/description.
- linear_createIssue must create an issue with status='active', a valid team_id/state_id pairing (state_id must belong to the same team), and priority within 0..4; it must append an issue_history event_type='created'.
- linear_updateIssue must write a corresponding issue_history row for each semantic change (state_changed/assigned/priority_changed/etc.); issue_history rows are immutable (no updates/deletes).
- linear_addIssueLabel inserts into issue_labels; if the label is already present it must be idempotent (no duplicate rows) and must still be safe under concurrency via unique(issue_id,label_id).
- linear_removeIssueLabel marks removal by deleting the join row or (if soft-delete is preferred) by recording a history event; in either case subsequent getLabels for the issue must not include removed labels.
- linear_assignIssue sets assignee_user_id; assigning a disabled/deleted user is forbidden; unassign is represented by setting assignee_user_id to null.
- linear_subscribeToIssue upserts issue_subscriptions(issue_id,user_id) with status='active'; unsubscribing sets status='unsubscribed' but retains the row for audit.
- linear_convertIssueToSubtask sets parent_issue_id; parent and child must be in the same team and org; cycles/projects are inherited only by explicit joins, not implicitly.
- linear_createIssueRelation creates an active directed edge; for symmetric semantics (e.g., blocks/blocked_by) the service must either store both directions or normalize types so queries can infer the inverse; self-relations are forbidden.
- linear_archiveIssue sets linear_issues.status='archived' and archived_at=now; archived issues cannot be modified except unarchive (status back to active) and comment creation if the upstream permits; history event_type='archived' is required.
- linear_setIssuePriority must enforce integer priority in [0,4] and record a history event_type='priority_changed'.
- linear_transferIssue changes team_id and must update identifier to the new team's key with a new sequence; state_id must be remapped to a state within the destination team; must record event_type='transferred_team'.
- linear_duplicateIssue creates a new issue row with a new linear_issue_id/identifier and copies title/description/labels (issue_labels) but not comments; it must record event_type='duplicated' on the new issue and may optionally reference the source in issue_relations (duplicates/duplicated_by).
- linear_createProject creates a project with status in ('planned','started','paused','completed','canceled','archived'); project name must be unique per org; updateProject must respect lifecycle (archived projects cannot be edited except unarchive if supported).
- linear_addIssueToProject and linear_addIssueToCycle must be idempotent via unique(project_id,issue_id) and unique(cycle_id,issue_id).
- linear_getActiveCycle returns the cycle with status='active' for a team; there must be at most one active cycle per team (enforced by a partial uniqueness constraint on cycles where status='active').