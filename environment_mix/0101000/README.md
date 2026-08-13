# MCP-Atlassian — local MCP environment

This backend stores Atlassian Cloud connection profiles plus a cached/replicated view of Jira and Confluence content to serve MCP tools for search, retrieval, and CRUD operations. Main workflows are: authenticate to an Atlassian site, sync or fetch Jira/Confluence objects on demand, apply mutations (create/update/delete/transition/link), and persist operation logs plus domain entities (issues, pages, comments, worklogs, attachments, boards/sprints).

Repository: https://github.com/sooperset/mcp-atlassian
Homepage: https://smithery.ai/server/mcp-atlassian

## Datastore

- `atlassian_connections.json` — Represents an authenticated connection to an Atlassian Cloud site (Jira + Confluence). All tool calls are scoped to a connection; tokens/credentials are referenced here and rotated. Also acts as the tenant boundary for all domain entities cached/stored in this backend. (12 rows; fields: ['id', 'org_name', 'site_base_url', 'cloud_id', 'auth_type', 'account_id', 'scopes', 'token_ref', 'status', 'last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked', 'error']
  - constraint: unique(site_base_url, account_id)
  - constraint: site_base_url must be a valid URL
  - constraint: scopes length >= 1
  - constraint: status != 'active' implies tools must not execute remote mutations
- `jira_entities.json` — Materialized Jira domain entities used by the MCP tools: projects, issues, fields, boards, sprints, worklogs, comments, attachments, and issue links. Stores minimal indexed fields for search plus a raw JSON snapshot to cover unknown/custom fields. (32 rows; fields: ['id', 'connection_id', 'entity_type', 'external_id', 'key', 'name', 'parent_external_id', 'project_external_id', 'issue_external_id', 'from_issue_external_id', 'to_issue_external_id', 'link_type', 'status_category', 'status_name', 'sprint_state', 'board_type', 'assignee_account_id', 'reporter_account_id', 'summary', 'description_text', 'body_text', 'time_spent_seconds', 'started_at', 'attachment_filename', 'attachment_mime_type', 'attachment_size_bytes', 'attachment_download_url', 'remote_updated_at', 'status', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'archived']
  - constraint: foreign key(connection_id) references atlassian_connections(id)
  - constraint: unique(connection_id, entity_type, external_id)
  - constraint: entity_type='issue' implies key is not null and project_external_id is not null
  - constraint: entity_type='worklog' implies issue_external_id is not null and time_spent_seconds >= 0
- `confluence_entities.json` — Materialized Confluence domain entities used by the MCP tools: pages and comments (including ancestry/children relationships). Stores indexed text for search plus a raw JSON snapshot for full fidelity. (32 rows; fields: ['id', 'connection_id', 'entity_type', 'external_id', 'space_key', 'title', 'body_text', 'parent_external_id', 'root_page_external_id', 'author_account_id', 'version_number', 'remote_updated_at', 'status', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'deleted', 'archived']
  - constraint: foreign key(connection_id) references atlassian_connections(id)
  - constraint: unique(connection_id, entity_type, external_id)
  - constraint: entity_type='page' implies title is not null
  - constraint: version_number is null or version_number >= 1
- `content_relations.json` — Explicit relationship edges to support navigation queries that the tools expose: Confluence page children/ancestors and Jira issue-to-epic, issue-to-parent (subtasks), board-to-sprint, sprint-to-issue, board-to-issue. While some of this is stored denormalized in entity rows, this table supports efficient graph queries and history. (32 rows; fields: ['id', 'connection_id', 'domain', 'relation_type', 'from_entity_external_id', 'to_entity_external_id', 'from_entity_type', 'to_entity_type', 'status', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: foreign key(connection_id) references atlassian_connections(id)
  - constraint: unique(connection_id, domain, relation_type, from_entity_external_id, to_entity_external_id)
  - constraint: from_entity_external_id != to_entity_external_id
  - constraint: domain='confluence' implies relation_type='confluence_parent_of'
- `tool_operations.json` — Immutable log of MCP tool invocations and their results for auditing, debugging, rate limiting, and replay protection. Stores request/response metadata and links to affected entities when known. (38 rows; fields: ['id', 'connection_id', 'tool_name', 'request', 'status', 'http_status', 'error_code', 'error_message', 'response_summary', 'affected_domain', 'affected_entity_type', 'affected_external_ids', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(connection_id) references atlassian_connections(id)
  - constraint: http_status between 100 and 599 when not null
  - constraint: finished_at >= started_at when both not null

## Business rules enforced by the tools

- All reads/writes must be scoped to a valid atlassian_connections row with status='active'; otherwise operations are rejected and logged with tool_operations.status='failed'.
- jira_get_issue must resolve by (connection_id, entity_type='issue', external_id) or (connection_id, entity_type='issue', key); on cache miss it may fetch remotely, upsert into jira_entities, and return the snapshot.
- jira_search and jira_get_project_issues/jira_get_epic_issues/jira_get_board_issues/jira_get_sprint_issues must store the executed query/JQL in tool_operations.request and store counts + returned issue ids in tool_operations.response_summary and tool_operations.affected_external_ids.
- jira_get_transitions must fetch transitions remotely and may store them in jira_entities.raw for the issue (entity_type='issue'); transition options are not persisted as first-class rows but must be reflected in operation logs.
- jira_add_comment creates a jira_entities row with entity_type='comment' tied to issue_external_id and must upsert the issue snapshot to reflect updated comment count in raw if provided.
- jira_add_worklog creates a jira_entities row with entity_type='worklog' tied to issue_external_id and must enforce time_spent_seconds >= 0; it must not create worklogs when the referenced issue status is 'deleted' in the cache.
- jira_download_attachments must only download attachments that exist as jira_entities rows (entity_type='attachment') or were returned by a fresh remote fetch; downloaded file bytes are not stored in the database, only metadata and the operation log.
- jira_create_issue and jira_batch_create_issues must create jira_entities rows with entity_type='issue' and unique (connection_id, entity_type, external_id) after remote success; local rows are not created if the remote call fails.
- jira_update_issue may change fields including epic/parent relationships; any resulting relationship changes must be reflected in content_relations using relation_type='jira_epic_of' and/or 'jira_parent_of' with status='active', and previous edges must be marked status='removed'.
- jira_transition_issue must validate that the requested transition id/name is present in the latest transitions fetched for the issue (from remote or cached issue raw); after remote success, issue.status_name/status_category and raw must be updated.
- jira_create_issue_link must create a jira_entities row with entity_type='issue_link' and also create a corresponding content_relations edge only if the link semantically corresponds to an existing relation_type supported by this backend; otherwise store link only in jira_entities.
- jira_remove_issue_link must mark the jira_entities issue_link row status='deleted' (never hard-delete) and set any corresponding content_relations edge status='removed'.
- jira_delete_issue must set jira_entities(entity_type='issue').status='deleted' after remote success and must cascade by marking related jira_entities rows (comments/worklogs/attachments/issue_link where issue_external_id matches) as 'archived' (not deleted) to preserve auditability.
- jira_search_fields must upsert jira_entities rows with entity_type='field' (unique by connection_id+external_id) and use name/key for fuzzy matching; raw stores full field schema.
- confluence_get_page must resolve by (connection_id, entity_type='page', external_id) with remote fetch+upsert on cache miss; returned content must come from confluence_entities.raw/body_text/title.
- confluence_get_page_children and confluence_get_page_ancestors must be served from content_relations where relation_type='confluence_parent_of' when available; on cache miss they may fetch remote hierarchy and upsert both confluence_entities and content_relations edges.
- confluence_get_comments must return confluence_entities rows with entity_type='comment' where parent_external_id matches the page external id; on cache miss it may fetch remotely and upsert.
- confluence_create_page must create a confluence_entities row with entity_type='page' status='current' and version_number >= 1 after remote success; it must also create/refresh the confluence_parent_of relation in content_relations when a parent is specified.
- confluence_update_page must increment version_number (remote truth) and update title/body_text/raw; it must reject updates if the cached status is 'deleted'.
- confluence_delete_page must set confluence_entities(entity_type='page').status='deleted' after remote success and mark its outgoing/incoming content_relations edges as status='removed'.
- For both Jira and Confluence entities, (connection_id, entity_type, external_id) uniqueness is enforced; upserts must be idempotent and must not create duplicate rows on retries.
- All tool invocations must write a tool_operations row; mutating tools must include affected_external_ids in the operation log after success.
- Rate limiting/quota is enforced per connection_id: no more than 60 remote Atlassian API calls per minute and no more than 10 concurrent tool_operations in status='running' per connection_id; violations must yield tool_operations.status='failed' with error_code='rate_limited'.