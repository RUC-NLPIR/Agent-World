# GitHub Projects — local MCP environment

This backend models GitHub Projects (V2) entities and the operations an integration server performs against GitHub’s GraphQL/REST APIs: managing projects, their fields/views, and project items (issues/PRs/drafts). It also stores connector-level state such as GitHub accounts, installation/auth tokens, and an audit log of tool actions to support listing, creating, updating, archiving, bulk operations, and conversions (draft -> issue).

Repository: https://github.com/devassistantai/mcp-servers
Homepage: https://smithery.ai/server/@devassistantai/github-projects

## Datastore

- `github_accounts.json` — Represents a GitHub identity (user or organization) that owns Projects V2 and is the scope for listing/creating projects. (12 rows; fields: ['id', 'github_node_id', 'login', 'account_type', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(github_node_id)
  - constraint: unique(login, account_type)
  - constraint: login length between 1 and 39
- `github_auth_connections.json` — Stores authentication material and connection health for making GitHub API calls on behalf of an account/installation. (12 rows; fields: ['id', 'account_id', 'auth_type', 'installation_id', 'token_ciphertext', 'token_expires_at', 'scopes', 'last_tested_at', 'last_error', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked', 'disabled']
  - constraint: fk(account_id) references github_accounts(id)
  - constraint: auth_type=github_app_installation implies installation_id is not null
  - constraint: status=active implies token_ciphertext is not null
  - constraint: token_expires_at must be null or > created_at
- `projects.json` — GitHub Projects (V2) mirrored into this service for listing and mutation, including archive state and basic metadata. (20 rows; fields: ['id', 'account_id', 'github_node_id', 'number', 'title', 'short_description', 'public', 'closed', 'status', 'archived_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: fk(account_id) references github_accounts(id)
  - constraint: unique(github_node_id)
  - constraint: unique(account_id, number)
  - constraint: title length between 1 and 256
- `project_schema.json` — Project fields and views (schema) for a GitHub Project V2. Stores both built-in and custom fields, field options, and view definitions used for grouping/filtering in the UI. (29 rows; fields: ['id', 'project_id', 'entity_type', 'github_node_id', 'name', 'field_data_type', 'field_is_builtin', 'field_required', 'parent_field_id', 'option_color', 'option_description', 'view_layout', 'view_query', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(project_id) references projects(id)
  - constraint: unique(github_node_id)
  - constraint: entity_type=field_option implies parent_field_id is not null
  - constraint: entity_type!=field_option implies parent_field_id is null
- `project_items.json` — Items within a Project V2: draft items or items linked to Issues/Pull Requests. Stores field values for update/group/status operations and supports conversion of drafts to issues. (39 rows; fields: ['id', 'project_id', 'github_node_id', 'item_type', 'content_github_node_id', 'repository_full_name', 'content_number', 'draft_title', 'draft_body', 'field_values', 'position', 'status', 'removed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: fk(project_id) references projects(id)
  - constraint: unique(github_node_id)
  - constraint: item_type in ('issue','pull_request') implies content_github_node_id is not null
  - constraint: item_type='draft' implies content_github_node_id is null
- `tool_action_logs.json` — Audit log of tool invocations and resulting GitHub mutations/reads for traceability, debugging, and idempotency (bulk operations, conversions, status changes). (36 rows; fields: ['id', 'account_id', 'auth_connection_id', 'project_id', 'tool_name', 'request_payload', 'response_payload', 'github_request_ids', 'idempotency_key', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: fk(account_id) references github_accounts(id)
  - constraint: tool_name in ('test_connection','list_projects','create_project','update_project','toggle_project_archive','update_project_item','remove_project_item','list_project_fields','list_project_views','list_project_items','add_project_item','create_draft_item','create_project_field','create_task','manage_task_status','group_tasks','convert_draft_to_issue','get_issue_id','bulk_add_issues')
  - constraint: unique(idempotency_key, tool_name) where idempotency_key is not null
  - constraint: status='failed' implies error_message is not null

## Business rules enforced by the tools

- test_connection must use an active github_auth_connections row; on success set last_tested_at=now() and status='active'; on auth failure set status to 'expired' or 'revoked' and persist last_error.
- list_projects returns projects for an account where projects.status in ('active','archived'); if local cache is stale, the service may refresh from GitHub and upsert by projects.github_node_id.
- create_project inserts a projects row with status='active' and must enforce unique(account_id, number) and unique(github_node_id) after the GitHub API returns IDs.
- update_project may only mutate projects where status='active' (unless updating archive state via toggle_project_archive) and must write updated_at.
- toggle_project_archive flips projects.status between 'active' and 'archived'; when archiving set archived_at=now(); when unarchiving set archived_at=null.
- list_project_fields reads project_schema where project_id matches and entity_type='field' and status='active'; list_project_views reads entity_type='view'.
- create_project_field inserts into project_schema with entity_type='field', status='active', and a supported field_data_type; if options are created (single_select), insert additional project_schema rows with entity_type='field_option' and parent_field_id referencing the field row.
- list_project_items returns project_items where project_id matches and status='active'; ordering may use position when present.
- add_project_item upserts project_items with item_type in ('issue','pull_request'); must set content_github_node_id and ensure unique(project_id, content_github_node_id) among active items by enforcing a derived uniqueness at write time (reject duplicates).
- create_draft_item inserts a project_items row with item_type='draft' and draft_title required; content_github_node_id must remain null until converted.
- update_project_item updates project_items.field_values and/or draft_title/draft_body; it must validate that any updated field value corresponds to an active project_schema field for that project and that single_select values reference an active field_option under that field.
- remove_project_item sets project_items.status='removed' and removed_at=now(); removed items must not be returned by list_project_items.
- create_task creates either a draft item (project_items.item_type='draft') or a real GitHub issue; in the real-issue path it must also ensure the resulting issue is added to the project (project_items.item_type='issue') and link content_github_node_id.
- manage_task_status must locate the target item (draft or issue) in project_items and set a designated 'Status' field in field_values; if a comment is provided and the item is an issue, it must be posted to GitHub and logged in tool_action_logs.
- group_tasks must apply the same validated field value update across multiple project_items rows in the same project; partial failure must be recorded in tool_action_logs with per-item errors in response_payload.
- convert_draft_to_issue may only run when project_items.item_type='draft' and status='active'; on success it must set item_type='issue', populate content_github_node_id, repository_full_name, content_number, and clear draft-only fields as appropriate.
- get_issue_id must resolve and return content_github_node_id for a project_items row where item_type='issue' and status='active'; if input refers to repo/number, it must be looked up and then mapped into the project item if present.
- bulk_add_issues must create multiple project_items for issues; it must be idempotent when an idempotency_key is provided by reusing the prior tool_action_logs entry and not duplicating active items.