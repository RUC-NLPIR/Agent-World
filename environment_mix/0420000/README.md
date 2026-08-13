# Plane Server — local MCP environment

Plane Server stores workspaces, users and their memberships, plus projects and project configuration (issue types, states, labels). It tracks delivery artifacts (modules, cycles) and the core work item (issues) with comments and worklogs, including many-to-many assignment of issues to modules and cycles and readable identifiers like ABC-123.

Repository: https://github.com/makeplane/plane-mcp-server
Homepage: https://smithery.ai/server/@makeplane/plane-mcp-server

## Datastore

- `users.json` — End users who can authenticate and act within workspaces; returned by get_user and referenced by authorship/audit fields. (18 rows; fields: ['id', 'email', 'display_name', 'avatar_url', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(email)
  - constraint: email must be a valid email format
  - constraint: display_name length between 1 and 200 chars
- `workspaces.json` — Top-level tenant boundary. Projects and memberships live under a workspace; get_workspace_members enumerates workspace_users. (18 rows; fields: ['id', 'slug', 'name', 'owner_user_id', 'status', 'created_at', 'updated_at', 'created_by_user_id', 'updated_by_user_id'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(slug)
  - constraint: slug matches ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$
  - constraint: name length between 1 and 200 chars
  - constraint: FK(owner_user_id) references users(id)
- `workspace_users.json` — Membership and roles for users in a workspace; drives get_workspace_members authorization checks. (18 rows; fields: ['id', 'workspace_id', 'user_id', 'role', 'status', 'invited_by_user_id', 'joined_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['invited', 'active', 'removed']
  - constraint: unique(workspace_id, user_id)
  - constraint: FK(workspace_id) references workspaces(id)
  - constraint: FK(user_id) references users(id)
  - constraint: role in ('owner','admin','member','viewer')
- `projects.json` — Projects inside a workspace. Contains configuration and counters for readable issue identifiers; supports get_projects and create_project. (18 rows; fields: ['id', 'workspace_id', 'identifier', 'name', 'description', 'status', 'issue_number_seq', 'default_state_id', 'created_at', 'updated_at', 'created_by_user_id', 'updated_by_user_id'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(workspace_id, identifier)
  - constraint: identifier matches ^[A-Z][A-Z0-9]{1,9}$
  - constraint: unique(workspace_id, name)
  - constraint: issue_number_seq >= 1
- `project_entities.json` — Unified storage for project-scoped objects: issue_types, states, labels, modules, and cycles. This reduces collection count while still modeling real domain and supports list/get/create/update/delete for each entity type. (18 rows; fields: ['id', 'project_id', 'entity_type', 'name', 'description', 'status', 'sort_order', 'color', 'state_category', 'is_default', 'cycle_start_at', 'cycle_end_at', 'module_lead_user_id', 'created_at', 'updated_at', 'created_by_user_id', 'updated_by_user_id'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: FK(project_id) references projects(id)
  - constraint: unique(project_id, entity_type, name) where status != 'deleted'
  - constraint: color matches ^#?[0-9A-Fa-f]{6}$ when not null
  - constraint: When entity_type='state': state_category is required and in allowed enum
- `issues.json` — Core work items plus their related comments, worklogs, and membership in modules/cycles via embedded child arrays. Supports create_issue/update_issue/get_issue_using_readable_identifier, issue comments and worklogs, and adding/removing issues from modules/cycles including cycle transfer. (21 rows; fields: ['id', 'project_id', 'issue_number', 'readable_identifier', 'title', 'description', 'status', 'state_id', 'issue_type_id', 'priority', 'assignee_user_ids', 'label_ids', 'module_ids', 'cycle_ids', 'comments', 'worklogs', 'created_at', 'updated_at', 'created_by_user_id', 'updated_by_user_id'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: FK(project_id) references projects(id)
  - constraint: unique(project_id, issue_number)
  - constraint: unique(project_id, readable_identifier)
  - constraint: readable_identifier must equal projects.identifier || '-' || issue_number (enforced by trigger or computed column)

## Business rules enforced by the tools

- get_user returns the users row for the authenticated principal; if users.status='disabled', all mutating tools must be rejected.
- get_workspace_members returns workspace_users rows for the current workspace context; caller must have workspace_users.status='active' in that workspace.
- get_projects returns projects where the caller has an active workspace_users membership in the owning workspace and the project.status != 'deleted' (no deleted state stored; use archived).
- create_project requires an active workspace membership with role in ('owner','admin'); projects.identifier must be unique per workspace and match ^[A-Z][A-Z0-9]{1,9}$.
- list_issue_types/list_states/list_labels/list_modules/list_cycles return project_entities filtered by project_id and entity_type and status != 'deleted'.
- get_issue_type/get_state/get_label/get_module/get_cycle must verify the referenced project_entities row exists, matches the requested entity_type, and belongs to the provided/derived project_id.
- create_state/create_issue_type must ensure exactly one default (is_default=true) per project and entity_type; setting a new default must unset the previous default in the same transaction.
- delete_* for project_entities performs a soft delete by setting status='deleted'; hard delete is disallowed if referenced by any issue (state_id, issue_type_id, label_ids, module_ids, cycle_ids).
- create_issue allocates projects.issue_number_seq atomically (SELECT FOR UPDATE / sequence) and writes issues.issue_number and issues.readable_identifier accordingly.
- get_issue_using_readable_identifier must locate the project by projects.identifier (project_identifier input) and then fetch the issue by (project_id, issue_number) where issue_number matches issue_identifier input; if multiple matches occur, treat as data corruption.
- update_issue must reject updates when issues.status='deleted' and must validate cross-project references (state_id/issue_type_id/label_ids/module_ids/cycle_ids cannot reference entities from another project).
- list_module_issues returns issues where the module id is contained in issues.module_ids and issues.status != 'deleted'. add_module_issues adds the module id to issues.module_ids idempotently; delete_module_issue removes it idempotently.
- list_cycle_issues returns issues where the cycle id is contained in issues.cycle_ids and issues.status != 'deleted'. add_cycle_issues adds the cycle id idempotently; delete_cycle_issue removes it idempotently.
- transfer_cycle_issues must, for each selected issue, remove from source cycle and add to destination cycle in a single transaction; destination and source cycles must be entity_type='cycle' and belong to same project.
- get_issue_comments returns issues.comments ordered by created_at ascending for the specified issue_id and project_id; add_issue_comment appends a comment with status='active' and sets audit fields.
- get_issue_worklogs returns issues.worklogs ordered by logged_at desc (or created_at desc if logged_at null). create_worklog appends a worklog with status='active' and time_spent_minutes within range.
- get_total_worklogs sums worklogs[*].time_spent_minutes for all issues in the project with issues.status != 'deleted' and worklogs[*].status='active'.
- update_worklog edits an embedded worklog by id; delete_worklog sets the embedded worklog status='deleted' (soft delete) rather than removing for auditability.