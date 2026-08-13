# Linear MCP Server — local MCP environment

This backend models a Linear-like issue tracker exposed through an MCP server, storing issues, users, teams/workflows, and comments. Core workflows include creating and updating issues, searching/filtering issues by common criteria (text, team, status, assignee, labels, priority, estimate), fetching a user's assigned issues, and adding markdown comments to issues.

Repository: https://github.com/jerhadf/linear-mcp-server
Homepage: https://smithery.ai/server/linear-mcp-server

## Datastore

- `users.json` — Human users who can be assigned issues and can author comments. Includes the authenticated user concept via an is_service_identity flag used by the MCP server. (25 rows; fields: ['id', 'email', 'display_name', 'avatar_url', 'is_service_identity', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(email) where email is not null
  - constraint: exactly_one(users.is_service_identity = true) (enforced at deploy time or via singleton constraint pattern)
- `teams.json` — Teams group issues and define workflow states available for issues in that team. (12 rows; fields: ['id', 'key', 'name', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(key)
  - constraint: unique(name)
- `workflow_states.json` — Per-team workflow states ("status") that issues can be in (e.g., Triage, In Progress, Done). Used by search filters and status updates. (32 rows; fields: ['id', 'team_id', 'name', 'type', 'position', 'is_default', 'is_resolved', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden']
  - constraint: foreign_key(team_id) references teams(id) on delete cascade
  - constraint: unique(team_id, name)
  - constraint: unique(team_id, position)
  - constraint: position >= 0
- `issues.json` — Issues (tickets) tracked in the system. Supports create/update, search, and per-user assignment queries. (37 rows; fields: ['id', 'team_id', 'identifier', 'number', 'title', 'description_md', 'assignee_id', 'creator_id', 'state_id', 'priority', 'estimate', 'labels', 'url', 'status', 'last_commented_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'closed', 'canceled', 'deleted']
  - constraint: foreign_key(team_id) references teams(id) on delete restrict
  - constraint: foreign_key(state_id) references workflow_states(id) on delete restrict
  - constraint: foreign_key(assignee_id) references users(id) on delete set null
  - constraint: foreign_key(creator_id) references users(id) on delete restrict
- `comments.json` — Comments posted on issues. Supports markdown body and optional custom author name/avatar overrides for the Linear MCP add_comment tool. (33 rows; fields: ['id', 'issue_id', 'author_user_id', 'custom_author_name', 'custom_author_avatar_url', 'body_md', 'url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['visible', 'deleted']
  - constraint: foreign_key(issue_id) references issues(id) on delete cascade
  - constraint: foreign_key(author_user_id) references users(id) on delete set null
  - constraint: url must be unique
  - constraint: body_md length between 1 and 20000

## Business rules enforced by the tools

- linear_create_issue must insert into issues with a valid team_id and state_id that belongs to the same team_id; if state_id is not provided by the tool implementation, it must use workflow_states.is_default=true for that team.
- On issue creation, issues.number must be allocated atomically per team (unique(team_id, number)); issues.identifier must equal teams.key || '-' || issues.number and be globally unique.
- linear_update_issue must only update fields that exist on issues: title, description_md, priority, estimate, labels, assignee_id, team_id, state_id, and status; it must reject updates that violate constraints (priority range, estimate >= 0, labels distinct).
- When updating issues.state_id, the referenced workflow_states.team_id must match issues.team_id; otherwise reject.
- Issue lifecycle status transitions must follow issues.lifecycle.transitions; attempts to update to an invalid next status must be rejected.
- linear_search_issues must support filtering by: text (matches issues.title or issues.description_md via full-text index), team (issues.team_id), status (either issues.status or issues.state_id depending on caller semantics; implementation must map 'status' filter to workflow_states.name and/or issues.status consistently), assignee (issues.assignee_id), labels (issues.labels contains any/all as implemented), priority (issues.priority), estimate (issues.estimate).
- linear_search_issues must enforce a maximum limit of 50 and default limit of 10; results must exclude issues.status='deleted'.
- linear_get_user_issues must select issues where assignee_id equals provided userId; if userId is omitted, use users.is_service_identity=true. Results must be sorted by issues.updated_at descending and exclude issues.status='deleted'.
- linear_add_comment must insert into comments with a valid issue_id referencing a non-deleted issue; it must set author_user_id to the authenticated user unless custom_author_name is provided (persona mode).
- After inserting a comment, issues.last_commented_at and issues.updated_at must be updated to the comment created_at, and the issue must remain searchable by updated_at ordering.
- Deleting/archiving teams or workflow states must not break FK integrity: teams.status='archived' prevents new issue creation in that team; workflow_states.status='hidden' prevents selecting that state for new issues but existing issues may remain in it.