# Jira MCP Server — local MCP environment

This backend models a lightweight Jira-connected MCP server that mirrors key Jira entities needed for issue CRUD and linking, plus caches Jira metadata (fields, issue types, link types) for fast listing. The main workflows are: create/update/delete issues, fetch project issues (including subtasks), resolve users by email to accountId, and create issue-to-issue links, all under a Jira connection context.

Repository: https://github.com/George5562/Jira-MCP-Server
Homepage: https://smithery.ai/server/@George5562/Jira-MCP-Server

## Datastore

- `jira_connections.json` — Represents a configured Jira site (cloud instance) the MCP server can act against, including authentication material references and sync settings used to cache metadata and map tool calls to the right Jira base URL. (12 rows; fields: ['id', 'status', 'display_name', 'cloud_id', 'base_url', 'auth_type', 'auth_secret_ref', 'default_project_key', 'metadata_last_synced_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(base_url)
  - constraint: base_url must be a valid URL
  - constraint: if status = 'error' then last_error is not null
- `jira_directory_users.json` — Cache of Jira users keyed by email to support get_user and attribution on created/updated issues. (29 rows; fields: ['id', 'connection_id', 'status', 'email', 'account_id', 'display_name', 'avatar_url', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'unknown']
  - constraint: unique(connection_id, email)
  - constraint: unique(connection_id, account_id)
  - constraint: email must be normalized to lowercase
  - constraint: account_id length >= 3
- `jira_metadata.json` — Cached Jira metadata used by list_fields, list_issue_types, and list_link_types. Stored per connection and per metadata kind. (31 rows; fields: ['id', 'connection_id', 'kind', 'status', 'jira_id', 'key', 'name', 'schema', 'extra', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(connection_id, kind, coalesce(jira_id,''), coalesce(key,''), name)
  - constraint: if kind = 'field' then key is not null
  - constraint: if kind = 'issue_type' then jira_id is not null
  - constraint: if kind = 'link_type' then name is not null
- `jira_issues.json` — Locally mirrored Jira issues (including subtasks) sufficient to serve get_issues and to provide referential integrity for create_issue_link and delete/update workflows. This is a cache/mirror and may lag Jira; write tools also upsert here after Jira API success. (34 rows; fields: ['id', 'connection_id', 'status', 'jira_issue_id', 'issue_key', 'project_key', 'issue_type_id', 'summary', 'description', 'reporter_account_id', 'assignee_account_id', 'parent_issue_key', 'is_subtask', 'fields_json', 'jira_updated_at', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'archived']
  - constraint: unique(connection_id, jira_issue_id)
  - constraint: unique(connection_id, issue_key)
  - constraint: issue_key must match pattern '^[A-Z][A-Z0-9_]+-[0-9]+$'
  - constraint: project_key must be non-empty
- `jira_issue_links.json` — Represents links between two Jira issues (blocks/relates/duplicates/etc.) created via create_issue_link and optionally mirrored from Jira. Supports link typing and directionality. (31 rows; fields: ['id', 'connection_id', 'status', 'jira_link_id', 'link_type_name', 'inward_issue_key', 'outward_issue_key', 'comment', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: inward_issue_key != outward_issue_key
  - constraint: unique(connection_id, link_type_name, inward_issue_key, outward_issue_key, status) where status='active'
  - constraint: if jira_link_id is not null then unique(connection_id, jira_link_id)
  - constraint: link_type_name must exist in jira_metadata where kind='link_type' and status='active' (per connection) at creation time

## Business rules enforced by the tools

- All tools operate within exactly one jira_connections row selected by server configuration; if multiple connections exist, a single active connection must be designated (e.g., by environment default) or the call must fail with a deterministic error.
- list_fields reads jira_metadata where kind='field' and connection_id matches the active connection; if metadata_last_synced_at is stale (implementation-defined, e.g., >24h) the service should refresh from Jira before responding or mark results as cached.
- list_issue_types reads jira_metadata where kind='issue_type' and status='active' for the active connection.
- list_link_types reads jira_metadata where kind='link_type' and status='active' for the active connection.
- get_user must return the account_id for a normalized lowercase email; if not present or status='unknown', the service must query Jira and upsert into jira_directory_users (unique by connection_id,email and connection_id,account_id).
- get_issues returns jira_issues filtered by connection_id and project_key (using jira_connections.default_project_key if a project key is not provided by the caller context); it must include subtasks by returning rows with parent_issue_key referencing an issue in the same project.
- create_issue must create the issue in Jira first; on success it must upsert a jira_issues row with status='active', set jira_issue_id and issue_key from Jira, store description/summary, and set last_synced_at to now.
- update_issue must update Jira first; on success it must update the corresponding jira_issues row (by connection_id and issue_key or jira_issue_id), bump updated_at, and set jira_updated_at/last_synced_at; attempts to update a locally 'deleted' issue must be rejected.
- delete_issue must delete the issue in Jira first; on success it must transition jira_issues.status from 'active' or 'archived' to 'deleted' and must not physically delete the row; subsequent deletes are idempotent and should succeed without further mutation.
- create_issue_link must verify both issue keys exist in jira_issues with status != 'deleted' (or fetch from Jira and upsert if missing) before calling Jira; on success it must insert into jira_issue_links with status='active' and enforce inward_issue_key != outward_issue_key.
- FK integrity: connection_id in all child collections must reference an existing jira_connections row; deletes of jira_connections are blocked if any child rows exist (restrict).