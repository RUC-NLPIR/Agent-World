# Jira MCP Server for Cursor — local MCP environment

This backend stores Jira server connections that users can add to the MCP server by signing in, along with the credentials/tokens needed to access Jira APIs. The main workflow is creating/managing authenticated Jira server connections (optionally per workspace/user), and using those connections for subsequent Jira operations (outside the provided tool surface).

Repository: https://github.com/kornbed/jira-mcp-server
Homepage: https://smithery.ai/server/@kornbed/jira-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace container for organizing Jira server connections and access control. (12 rows; fields: ['id', 'name', 'slug', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name <> ''
  - constraint: slug matches ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$
- `users.json` — End-users who can sign in and manage Jira server connections. (18 rows; fields: ['id', 'workspace_id', 'email', 'display_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(workspace_id, email)
  - constraint: email <> ''
- `jira_servers.json` — Configured Jira instances/servers that can be accessed by signing in (Cloud or self-hosted). (18 rows; fields: ['id', 'workspace_id', 'name', 'base_url', 'deployment_type', 'auth_type', 'status', 'last_verified_at', 'last_error', 'created_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'active', 'revoked', 'error', 'deleted']
  - constraint: unique(workspace_id, base_url)
  - constraint: unique(workspace_id, name)
  - constraint: base_url <> ''
  - constraint: name <> ''
- `jira_auth_sessions.json` — Short-lived sign-in sessions used to complete Jira authentication (OAuth/other flows) before persisting credentials. (18 rows; fields: ['id', 'workspace_id', 'user_id', 'jira_server_id', 'auth_type', 'status', 'state_token', 'redirect_uri', 'expires_at', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['initiated', 'awaiting_callback', 'completed', 'expired', 'cancelled', 'error']
  - constraint: unique(state_token)
  - constraint: expires_at > created_at
- `jira_credentials.json` — Stored credentials/tokens for accessing a Jira server. Sensitive fields are stored encrypted/hashed and access-controlled. (19 rows; fields: ['id', 'jira_server_id', 'workspace_id', 'user_id', 'auth_type', 'status', 'account_id', 'username', 'access_token_enc', 'refresh_token_enc', 'api_token_enc', 'token_expires_at', 'scopes', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'rotated', 'revoked']
  - constraint: unique(jira_server_id, user_id, auth_type, status) where status='active'
  - constraint: workspace_id must equal (select workspace_id from jira_servers where jira_servers.id=jira_server_id)
  - constraint: auth_type='oauth2' implies access_token_enc is not null
  - constraint: auth_type='oauth2' implies refresh_token_enc is not null

## Business rules enforced by the tools

- The single tool "Optional Settings" maps to managing Jira server sign-in and connection settings: creating/updating jira_servers, creating jira_auth_sessions, and persisting jira_credentials upon successful sign-in; because the tool has no parameters, all mutations must be driven by server-side configuration and interactive auth flow state stored in jira_auth_sessions.
- A workspace in status 'deleted' cannot create new jira_servers, jira_auth_sessions, or jira_credentials.
- jira_servers.base_url must be normalized (scheme + host, no trailing slash) before enforcing unique(workspace_id, base_url).
- Only one active credential per (jira_server_id, user_id, auth_type) is allowed; rotating credentials must set prior active credential to status='rotated' before inserting the new active credential.
- jira_auth_sessions must expire: any session with expires_at <= now must be transitioned to status='expired' and cannot be completed.
- A jira_server cannot be set to status='active' unless there exists at least one jira_credentials row with status='active' for that jira_server.
- Revoking access must set jira_credentials.status='revoked' and transition jira_servers.status to 'revoked' unless another active credential exists for that server.
- All secret-bearing fields (*_enc) must be stored encrypted at rest; plaintext secrets must never be persisted.
- FK integrity must be enforced: deleting a workspace must cascade jira_servers and jira_auth_sessions to status='deleted'/'expired' rather than physical deletion; jira_credentials should be set to status='revoked'.
- Audit fields updated_at must update on any mutation, including status transitions and last_used_at updates.