# Linear — local MCP environment

This backend stores a Linear workspace (organization) with users, teams, workflow states, projects, cycles and issues. Core workflows include listing and searching issues, creating/updating issues and projects, associating issues to projects/cycles/labels, managing assignments/subscriptions/relations, and recording issue history and comments for auditability.

Repository: https://github.com/tacticlaunch/mcp-linear
Homepage: https://smithery.ai/server/@tacticlaunch/mcp-linear

## Datastore

- `organizations.json` — Linear organization (workspace) and its high-level settings. Serves getOrganization and provides the parent scope for users/teams/projects/issues. (12 rows; fields: ['id', 'slug', 'name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name <> ''
- `accounts.json` — Users, teams, membership, viewer identity, labels, and workflow states. Designed as a compact but realistic model that supports listing users/teams/labels/workflow states and validating assignees and state transitions on issues. (29 rows; fields: ['id', 'organization_id', 'entity_type', 'status', 'name', 'key', 'email', 'is_viewer', 'team_id', 'user_id', 'role', 'state_category', 'position', 'color', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: CHECK(entity_type IN ('user','team','team_membership','label','workflow_state'))
  - constraint: CHECK((entity_type='user') = (email IS NOT NULL))
  - constraint: CHECK((entity_type='team') = (key IS NOT NULL))
  - constraint: CHECK((entity_type='team_membership') = (team_id IS NOT NULL AND user_id IS NOT NULL AND role IS NOT NULL))
- `planning.json` — Projects, cycles, and issue-to-project/cycle associations. Supports listing/creating/updating projects, listing cycles and active cycle, and adding/getting issues in a project or cycle. (35 rows; fields: ['id', 'organization_id', 'entity_type', 'status', 'team_id', 'name', 'description', 'start_at', 'end_at', 'project_id', 'cycle_id', 'issue_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'planned', 'completed', 'canceled', 'archived', 'deleted']
  - constraint: CHECK(entity_type IN ('project','cycle','project_issue','cycle_issue'))
  - constraint: CHECK((entity_type='cycle') = (team_id IS NOT NULL AND start_at IS NOT NULL AND end_at IS NOT NULL))
  - constraint: CHECK((entity_type='project') = (name IS NOT NULL))
  - constraint: CHECK((entity_type='project_issue') = (project_id IS NOT NULL AND issue_id IS NOT NULL))
- `issues.json` — Issues (tickets) including identifiers, state, priority, assignee, parent/subtask structure, labels, subscriptions, comments and relations. Supports all issue CRUD/search and the various mutation tools. (38 rows; fields: ['id', 'organization_id', 'team_id', 'number', 'identifier', 'title', 'description', 'priority', 'estimate', 'state_id', 'assignee_id', 'creator_id', 'parent_issue_id', 'archived_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(team_id, number) WHERE status <> 'deleted'
  - constraint: unique(team_id, identifier) WHERE status <> 'deleted'
  - constraint: CHECK(number > 0)
  - constraint: CHECK(priority IN (0,1,2,3,4))
- `issue_activity.json` — Child/association records for issues: comments, labels applied to issues, subscriptions, relations between issues, and immutable history/audit events. Supports createComment/getComments, add/remove label, subscribe, create relation, duplicate tracking, and issue history. (31 rows; fields: ['id', 'organization_id', 'entity_type', 'status', 'issue_id', 'user_id', 'body', 'label_id', 'related_issue_id', 'relation_type', 'event_type', 'event_payload', 'source_issue_id', 'duplicate_issue_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: CHECK(entity_type IN ('comment','issue_label','issue_subscription','issue_relation','issue_history_event','issue_duplicate_link'))
  - constraint: CHECK((entity_type='comment') = (body IS NOT NULL AND user_id IS NOT NULL))
  - constraint: CHECK((entity_type='issue_label') = (label_id IS NOT NULL))
  - constraint: CHECK((entity_type='issue_subscription') = (user_id IS NOT NULL))

## Business rules enforced by the tools

- linear_getViewer returns the single accounts row where entity_type='user' AND is_viewer=true AND status='active' for the current organization context.
- linear_getOrganization returns the organizations row in status='active' for the current auth context; if suspended, read tools may still return it but write tools must be rejected.
- linear_getUsers returns accounts rows where entity_type='user' AND organization_id matches AND status='active'.
- linear_getTeams returns accounts rows where entity_type='team' AND organization_id matches AND status='active'.
- linear_getLabels returns accounts rows where entity_type='label' AND organization_id matches AND status='active'.
- linear_getWorkflowStates returns accounts rows where entity_type='workflow_state' AND team_id is a team in the org AND status='active', ordered by position asc.
- Creating an issue (linear_createIssue) must: (a) allocate the next number atomically per team_id, (b) set identifier to <team.key>-<number>, (c) set creator_id to viewer if not provided, (d) require state_id that belongs to the same team.
- linear_getIssues returns issues where organization_id matches AND status='active', ordered by updated_at desc (recent).
- linear_getIssueById must accept either issues.id or issues.identifier; if both match different rows, prefer exact id match.
- linear_searchIssues must filter over issues fields (team_id, state_id, assignee_id, priority, status, created_at/updated_at) and may full-text match title/description; it must not return status='deleted'.
- linear_updateIssue may modify title/description/state_id/assignee_id/priority/estimate/parent_issue_id but must append an issue_history_event capturing before/after for each change.
- linear_archiveIssue sets issues.status='archived' and issues.archived_at=now(); unarchive (if exposed via update) sets status='active' and archived_at=NULL; both actions write issue_history_event.
- linear_setIssuePriority updates issues.priority and records issue_history_event(event_type='priority_changed').
- linear_assignIssue updates issues.assignee_id and records issue_history_event(event_type='assignee_changed'); assignee must be an active user in the same organization.
- linear_convertIssueToSubtask sets issues.parent_issue_id and records issue_history_event(event_type='converted_to_subtask'); parent must be in same organization; parent_issue_id cannot create cycles (must remain a tree).
- linear_transferIssue changes issues.team_id and re-numbers the issue within the destination team, updating identifier accordingly; it must also ensure state_id is moved to a valid workflow_state in the destination team; it records issue_history_event(event_type='transferred') with from_team_id/to_team_id and old/new identifiers.
- linear_duplicateIssue creates a new issues row copying fields (title, description, priority, estimate, labels optionally as issue_label rows) and creates an issue_duplicate_link plus issue_history_event(event_type='duplicated') for both source and duplicate.
- linear_createComment inserts issue_activity row entity_type='comment' with issue_id, user_id=viewer, body; also inserts issue_history_event(event_type='updated') or (event_type='created' for first comment is not allowed) and bumps issues.updated_at.
- linear_getComments returns issue_activity rows entity_type='comment' AND issue_id matches AND status='active', ordered by created_at asc.
- linear_addIssueLabel inserts issue_activity row entity_type='issue_label' with (issue_id,label_id); label must be active; duplicates are prevented by the unique constraint; also writes issue_history_event(event_type='label_added').
- linear_removeIssueLabel marks the corresponding issue_activity issue_label row status='deleted' (soft-delete) and writes issue_history_event(event_type='label_removed').
- linear_subscribeToIssue inserts issue_activity row entity_type='issue_subscription' for (issue_id,user_id=viewer); duplicates prevented; unsubscribing (not exposed) would set status='deleted'.
- linear_createIssueRelation inserts issue_activity row entity_type='issue_relation' with (issue_id, related_issue_id, relation_type) and writes issue_history_event(event_type='relation_created'); for symmetric types, the API layer may also create the inverse relation (e.g. blocks implies blocked_by).
- Projects: linear_createProject inserts planning row entity_type='project'; linear_updateProject updates it; both require organization status='active' and record updated_at.
- linear_addIssueToProject creates planning row entity_type='project_issue' referencing project_id and issue_id; it must be unique and records issue_history_event(event_type='added_to_project').
- linear_getProjectIssues returns issues joined through planning where entity_type='project_issue' AND project_id matches AND association status='active' AND issues.status<>'deleted'.
- Cycles: linear_getCycles returns planning rows entity_type='cycle' (optionally filtered by team in API layer) where status<>'deleted'.
- linear_getActiveCycle returns the single planning cycle row for a team where start_at <= now() < end_at AND status='active'; if multiple match, prefer the one with latest start_at.
- linear_addIssueToCycle creates planning row entity_type='cycle_issue' (cycle_id, issue_id) unique and records issue_history_event(event_type='added_to_cycle').
- linear_getIssueHistory returns issue_activity rows entity_type='issue_history_event' for the issue, ordered by created_at asc; history rows are immutable (updates disallowed except soft-delete for legal requests).