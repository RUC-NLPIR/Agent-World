# Atlassian Integration Server — local MCP environment

This backend stores tenant/workspace connections to Atlassian (Jira + Confluence), plus cached representations of Jira issues/boards/sprints and Confluence pages and their child entities (comments, labels, worklogs, attachments, links). The main workflows are: authenticate/connect a workspace to Atlassian, perform read/search operations from cache with optional refresh, and perform write operations (create/update/delete/transition/link) that sync to Atlassian and then update the local cache and audit history.

Repository: https://github.com/ayasahmad/mcp-atlassian
Homepage: https://smithery.ai/server/@ayasahmad/mcp-atlassian3

## Datastore

- `workspaces.json` — Tenant boundary for the integration server. Holds configuration like read-only mode and default limits, and is the parent for Atlassian connections and cached objects. (12 rows; fields: ['workspace_id', 'name', 'status', 'read_only_mode', 'default_page_size', 'max_page_size', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_page_size >= 1
  - constraint: max_page_size BETWEEN 1 AND 200
  - constraint: default_page_size <= max_page_size
- `atlassian_connections.json` — Stores Atlassian Cloud/Server connection details per workspace (Jira and/or Confluence), including auth material and last sync timestamps used by all tools. (12 rows; fields: ['connection_id', 'workspace_id', 'product', 'deployment', 'base_url', 'auth_type', 'auth_principal', 'auth_secret_ref', 'status', 'last_verified_at', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: fk(workspace_id) references workspaces(workspace_id) on delete cascade
  - constraint: unique(workspace_id, product)
  - constraint: base_url must be a valid URL string
  - constraint: auth_secret_ref is required and must match secret-store key format
- `jira_entities.json` — Cache and local state for Jira domain objects needed by the tool surface: users (profile), projects, issues, boards, sprints, issue links, attachments, comments, worklogs, and changelogs. A single collection is used with a typed payload to keep total collections within limits while still mapping every tool parameter to stored fields. (17 rows; fields: ['jira_entity_id', 'workspace_id', 'connection_id', 'entity_type', 'external_id', 'external_key', 'parent_external_id', 'status', 'title', 'body', 'json_payload', 'indexed_text', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'tombstoned']
  - constraint: fk(workspace_id) references workspaces(workspace_id) on delete cascade
  - constraint: fk(connection_id) references atlassian_connections(connection_id) on delete cascade
  - constraint: unique(workspace_id, connection_id, entity_type, external_id)
  - constraint: external_key is required when entity_type in ('issue','project')
- `confluence_entities.json` — Cache and local state for Confluence domain objects required by tools: pages, comments, labels, and spaces. Stores both rendered/raw content and markdown-converted content when requested. (18 rows; fields: ['confluence_entity_id', 'workspace_id', 'connection_id', 'entity_type', 'external_id', 'space_key', 'parent_external_id', 'status', 'title', 'content_format', 'content', 'metadata_json', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'deleted', 'tombstoned']
  - constraint: fk(workspace_id) references workspaces(workspace_id) on delete cascade
  - constraint: fk(connection_id) references atlassian_connections(connection_id) on delete cascade
  - constraint: unique(workspace_id, connection_id, entity_type, external_id)
  - constraint: connection_id must refer to a row with product='confluence'
- `tool_requests.json` — Audit log and idempotency layer for all tool calls (read and write). Stores tool name, parameters, result/error, and links to affected cached entities. Enables debugging, rate-limiting, and consistent behavior across refresh/expand/convert_to_markdown options. (21 rows; fields: ['tool_request_id', 'workspace_id', 'connection_id', 'tool_name', 'params_json', 'status', 'http_status', 'error_code', 'error_message', 'result_json', 'affected_entities', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'rejected']
  - constraint: fk(workspace_id) references workspaces(workspace_id) on delete cascade
  - constraint: tool_name must be one of the 35 exposed tools
  - constraint: http_status BETWEEN 100 AND 599 when not null
  - constraint: finished_at >= started_at when both not null

## Business rules enforced by the tools

- All tools must resolve a workspace; if workspace.status != 'active' then all tools are rejected with status='rejected' and error_code='WORKSPACE_INACTIVE'.
- Mutating tools (jira_create_issue, jira_batch_create_issues, jira_update_issue, jira_delete_issue, jira_add_comment, jira_add_worklog, jira_link_to_epic, jira_create_issue_link, jira_remove_issue_link, jira_transition_issue, jira_create_sprint, jira_update_sprint, confluence_add_label, confluence_create_page, confluence_update_page, confluence_delete_page, jira_download_attachments) must be rejected when workspaces.read_only_mode = true.
- Each workspace can have at most one active connection per product: unique(workspace_id, product) in atlassian_connections; tools requiring Jira/Confluence must use the matching product connection with status='active' or fail with error_code='UPSTREAM_UNAVAILABLE'.
- jira_batch_get_changelogs must be rejected with error_code='NOT_IMPLEMENTED' when atlassian_connections.deployment='server'.
- Pagination parameters must be enforced: limit defaults to workspaces.default_page_size, limit must be between 1 and workspaces.max_page_size (Confluence search additionally caps to 50), and start_at/start must be >= 0.
- jira_search must store the executed jql, fields, expand, start_at, limit, projects_filter in tool_requests.params_json; the returned issue set must correspond to jira_entities rows with entity_type='issue' (creating/updating cache entries as needed).
- jira_get_issue must be keyed by issue_key; it must map to jira_entities where entity_type='issue' and external_key=issue_key. If not present or stale, the system fetches upstream and upserts json_payload and fetched_at.
- jira_get_transitions and jira_transition_issue must validate that transition_id exists in the latest fetched transitions for the issue (from json_payload/expand or separate fetch); invalid transition_id yields error_code='INVALID_TRANSITION'.
- jira_create_issue_link must validate link_type exists in cached jira_entities where entity_type='link_type' (or fetched on demand via jira_get_link_types); missing yields error_code='INVALID_LINK_TYPE'.
- jira_remove_issue_link must require link_id and must tombstone the corresponding jira_entities row with entity_type='issue_link' (status transition active->deleted) after upstream success.
- jira_download_attachments must only download attachments referenced by jira_entities(entity_type='attachment') with parent_external_id matching the issue external_id; each download attempt must be logged in tool_requests with params_json.target_dir.
- confluence_get_page and confluence_get_page_children must honor convert_to_markdown: if true, confluence_entities.content_format='markdown' and content is stored as markdown; otherwise content_format='html'.
- confluence_add_label must enforce uniqueness of (workspace_id, connection_id, entity_type='label', parent_external_id=page_id, title=name) by upserting or rejecting duplicates; the resulting label list must reflect all active labels for that page.
- confluence_delete_page must mark the confluence_entities page row as status='deleted' (and optionally tombstone descendants asynchronously) only after upstream deletion succeeds.
- jira_search_fields must support refresh=true: when refresh is true, tool implementation must re-fetch field definitions upstream and update jira_entities rows where entity_type='project'/'issue' field metadata is embedded in json_payload/indexed_text; it must record refresh in tool_requests.params_json.refresh=true.