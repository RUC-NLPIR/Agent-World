# Jira Sprint Dashboard — local MCP environment

This backend stores OAuth connection state for a user to an Atlassian Jira Cloud site, plus cached Jira metadata (projects, issues, and search executions) to power a sprint health/dashboard experience. Main workflows are: user completes OAuth, the service validates connectivity, then issues can be fetched by key or searched by JQL with results cached for performance and auditability.

Repository: https://github.com/CHIBOLAR/jira_mcp_sprinthealth
Homepage: https://smithery.ai/server/@CHIBOLAR/jira_mcp_sprinthealth

## Datastore

- `users.json` — End-users of the MCP server. Used to associate OAuth sessions/tokens and query history to an actor. (18 rows; fields: ['id', 'display_name', 'email', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: status IN ('active','disabled','deleted')
  - constraint: email IS NULL OR email LIKE '%@%زوج' (application-level email validation; DB may use a CHECK or skipped)
  - constraint: created_at <= updated_at
- `jira_connections.json` — OAuth connection to Atlassian/Jira for a given user, including token material and the selected Jira cloud (site) and API base URLs. (18 rows; fields: ['id', 'user_id', 'atlassian_account_id', 'cloud_id', 'jira_base_url', 'scopes', 'access_token_ciphertext', 'refresh_token_ciphertext', 'token_expires_at', 'last_tested_at', 'last_error', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['unauthenticated', 'oauth_in_progress', 'active', 'expired', 'revoked', 'error']
  - constraint: FK(user_id) REFERENCES users(id) ON DELETE CASCADE
  - constraint: UNIQUE(user_id) -- one active connection record per user (tokens rotate inside the same row)
  - constraint: status IN ('unauthenticated','oauth_in_progress','active','expired','revoked','error')
  - constraint: token_expires_at IS NULL OR token_expires_at > created_at
- `oauth_sessions.json` — Short-lived browser OAuth flow sessions created by start_oauth; tracks state/PKCE/verifier and completion outcome to support oauth_status polling. (18 rows; fields: ['id', 'user_id', 'jira_connection_id', 'oauth_state', 'pkce_code_verifier_ciphertext', 'authorization_url', 'redirect_uri', 'status', 'error', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'browser_opened', 'callback_received', 'exchanged', 'failed', 'expired', 'cancelled']
  - constraint: FK(user_id) REFERENCES users(id) ON DELETE CASCADE
  - constraint: FK(jira_connection_id) REFERENCES jira_connections(id) ON DELETE CASCADE
  - constraint: UNIQUE(oauth_state) -- must be globally unique to prevent replay
  - constraint: expires_at > created_at
- `jira_projects.json` — Cached Jira projects accessible via the authenticated connection. Populated/updated by list_projects and used to avoid repeated remote calls. (18 rows; fields: ['id', 'jira_connection_id', 'jira_project_id', 'project_key', 'name', 'project_type_key', 'archived', 'deleted', 'last_synced_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'disabled']
  - constraint: FK(jira_connection_id) REFERENCES jira_connections(id) ON DELETE CASCADE
  - constraint: UNIQUE(jira_connection_id, jira_project_id)
  - constraint: UNIQUE(jira_connection_id, project_key)
  - constraint: project_key <> ''
- `jira_issues.json` — Cached Jira issues fetched via jira_get_issue or returned in jira_search results. Stores a normalized subset for dashboarding plus raw JSON for completeness. (20 rows; fields: ['id', 'jira_connection_id', 'jira_issue_id', 'issue_key', 'project_key', 'issue_type', 'summary', 'status_name', 'assignee_account_id', 'reporter_account_id', 'priority', 'labels', 'sprint_name', 'story_points', 'raw_issue_json', 'last_fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted', 'forbidden']
  - constraint: FK(jira_connection_id) REFERENCES jira_connections(id) ON DELETE CASCADE
  - constraint: UNIQUE(jira_connection_id, jira_issue_id)
  - constraint: UNIQUE(jira_connection_id, issue_key)
  - constraint: issue_key <> ''
- `jira_searches.json` — Audit log of JQL searches executed via jira_search, including the query, pagination, and a lightweight snapshot of results (issue keys/ids). (18 rows; fields: ['id', 'jira_connection_id', 'user_id', 'jql', 'start_at', 'max_results', 'returned_count', 'total', 'result_issue_keys', 'result_issue_ids', 'executed_at', 'duration_ms', 'status', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'throttled']
  - constraint: FK(jira_connection_id) REFERENCES jira_connections(id) ON DELETE CASCADE
  - constraint: FK(user_id) REFERENCES users(id) ON DELETE CASCADE
  - constraint: jql <> ''
  - constraint: start_at >= 0

## Business rules enforced by the tools

- oauth_status returns the latest jira_connections row for the current user and, if present, the most recent oauth_sessions row with status in ('created','browser_opened','callback_received'); if token_expires_at < now() then connection status must be set to 'expired'.
- start_oauth must create a new oauth_sessions row with a unique oauth_state, status='created', expires_at between now()+5min and now()+30min, and must transition the related jira_connections.status to 'oauth_in_progress'.
- When the OAuth callback is exchanged successfully (out-of-band to the tool surface), the service must set oauth_sessions.status='exchanged' and jira_connections.status='active', store encrypted tokens, token_expires_at, granted scopes, cloud_id, and jira_base_url.
- test_jira_connection must only succeed if jira_connections.status IN ('active','expired') and a valid access token is present or can be refreshed; on success set last_tested_at=now(), last_error=NULL, and status='active'. On 401/invalid_grant set status to 'revoked' or 'expired' accordingly and persist last_error.
- jira_get_issue must require jira_connections.status='active' (or refresh to become active). The fetched issue must upsert into jira_issues by (jira_connection_id, issue_key) and update last_fetched_at and raw_issue_json; if Jira returns 404 mark status='deleted', if 403 mark status='forbidden'.
- jira_search must require an active connection (or refresh). Each search execution must insert a jira_searches row capturing jql, pagination (default start_at=0, max_results=50 at application layer), duration_ms, and result issue ids/keys; issues returned must be upserted into jira_issues.
- list_projects must require an active connection (or refresh). Projects returned must upsert into jira_projects by (jira_connection_id, jira_project_id) and set last_synced_at=now(); projects not seen for >30 days may be marked status='stale' by a background job.
- help is static and does not mutate storage; however, requests may be logged at the application layer without adding a new collection.
- Token material fields (access_token_ciphertext, refresh_token_ciphertext, pkce_code_verifier_ciphertext) must be encrypted at rest and never returned by any tool.
- A user in status='disabled' or 'deleted' must not be allowed to start OAuth, test Jira connection, search, list projects, or fetch issues; attempts should fail with an authorization error.