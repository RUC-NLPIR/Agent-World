# BigQuery — local MCP environment

This backend stores connection metadata and access governance for a BigQuery MCP server, including server registrations, authentication sessions, and issued API keys. The primary workflow is: an operator registers a server configuration, users sign in to create sessions, and the system enforces access controls and auditability for subsequent BigQuery operations (even if the current tool surface only exposes optional settings).

Repository: https://github.com/ergut/mcp-bigquery-server
Homepage: https://smithery.ai/server/@ergut/mcp-bigquery-server

## Datastore

- `servers.json` — Registered BigQuery server instances/configurations the MCP service can connect to and manage. (12 rows; fields: ['id', 'display_name', 'project_id', 'location', 'auth_mode', 'service_account_email', 'secret_ref', 'scopes', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(display_name)
  - constraint: project_id <> ''
  - constraint: auth_mode in ('service_account_json','adc','oauth_user')
  - constraint: status in ('active','disabled','deleted')
- `users.json` — Principals that can sign in to manage or use the BigQuery MCP server. (31 rows; fields: ['id', 'email', 'display_name', 'role', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(email)
  - constraint: role in ('owner','admin','member','viewer')
  - constraint: status in ('active','suspended','deleted')
- `auth_sessions.json` — User sign-in sessions used to access and manage servers (maps to the tool description: 'Access and manage servers by signing in.'). (34 rows; fields: ['id', 'user_id', 'server_id', 'auth_provider', 'access_token_hash', 'refresh_token_ref', 'expires_at', 'ip_address', 'user_agent', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: fk(user_id) references users(id)
  - constraint: server_id is null or fk(server_id) references servers(id)
  - constraint: expires_at > created_at
  - constraint: status in ('active','revoked','expired')
- `api_keys.json` — API keys used by clients/agents to authenticate to the MCP server and manage BigQuery server connections. (35 rows; fields: ['id', 'user_id', 'server_id', 'name', 'key_prefix', 'key_hash', 'last_used_at', 'expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: fk(user_id) references users(id)
  - constraint: server_id is null or fk(server_id) references servers(id)
  - constraint: unique(key_hash)
  - constraint: unique(user_id, name)
- `settings.json` — Optional server/user settings surfaced by the MCP tool 'Optional Settings'. Stored as key-value JSON with scoping and auditability. (35 rows; fields: ['id', 'scope_type', 'server_id', 'user_id', 'key', 'value', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: scope_type in ('global','server','user')
  - constraint: status in ('active','archived')
  - constraint: scope_type='global' implies (server_id is null and user_id is null)
  - constraint: scope_type='server' implies (server_id is not null and user_id is null)

## Business rules enforced by the tools

- The 'Optional Settings' tool (with empty parameters) must only return settings visible to the authenticated principal: global settings plus settings for their user_id, plus settings for any server_id they are authorized to manage/use.
- Creating or updating a server configuration requires an active user with role in ('owner','admin').
- A user with status != 'active' cannot create new auth_sessions or api_keys; existing sessions must be transitioned to revoked/expired upon user suspension/deletion.
- A server with status != 'active' cannot be the target of new auth_sessions or api_keys; disabling a server should revoke active sessions scoped to that server.
- No raw secrets (API keys, OAuth tokens, service account JSON) may be stored; only hashes or secret_ref/refresh_token_ref pointers are allowed.
- Status transitions must follow the lifecycle transition maps defined per collection; direct writes that violate transitions must be rejected.
- For settings, at most one active row may exist per (scope_type, server_id, user_id, key); updates should archive the prior active row and insert a new active row for auditability.