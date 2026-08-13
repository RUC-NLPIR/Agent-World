# CData Connect Cloud MCP Server — local MCP environment

This backend stores identities, organizations, and authenticated sessions for accessing and managing CData Connect Cloud servers. The primary workflow is a user/agent signs in to an organization, receives a session, and uses that session to enumerate and manage server connections and related settings.

Repository: https://github.com/CDataSoftware/connectcloud-mcp-server
Homepage: https://smithery.ai/server/@CDataSoftware/connectcloud-mcp-server

## Datastore

- `organizations.json` — Tenant boundary representing a company/account in CData Connect Cloud. Owns users, API clients, and servers. (12 rows; fields: ['id', 'name', 'slug', 'status', 'plan', 'region', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name <> ''
  - constraint: slug <> ''
- `users.json` — Human users who can sign in and manage servers within an organization. (18 rows; fields: ['id', 'organization_id', 'email', 'display_name', 'role', 'status', 'password_hash', 'mfa_enabled', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['invited', 'active', 'disabled', 'deleted']
  - constraint: unique(organization_id, email)
  - constraint: email <> ''
  - constraint: role in ('owner','admin','member','read_only')
  - constraint: mfa_enabled in (true,false)
- `servers.json` — CData Connect Cloud server instances or logical endpoints managed under an organization. Sessions grant access to manage these servers. (12 rows; fields: ['id', 'organization_id', 'name', 'base_url', 'environment', 'status', 'settings', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'online', 'offline', 'error', 'deleted']
  - constraint: unique(organization_id, name)
  - constraint: unique(organization_id, base_url)
  - constraint: name <> ''
  - constraint: base_url <> ''
- `api_clients.json` — Non-human clients (e.g., MCP server agent) that can sign in to an organization using a client_id/client_secret or token exchange to create sessions. (12 rows; fields: ['id', 'organization_id', 'name', 'client_key', 'client_secret_hash', 'scopes', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'deleted']
  - constraint: unique(organization_id, name)
  - constraint: unique(client_key)
  - constraint: name <> ''
  - constraint: client_key <> ''
- `auth_sessions.json` — Authenticated sessions created after sign-in. Used by the MCP server to access and manage servers; holds tokens/refresh metadata and optional selected server context. (20 rows; fields: ['id', 'organization_id', 'user_id', 'api_client_id', 'selected_server_id', 'access_token_hash', 'refresh_token_hash', 'expires_at', 'status', 'ip_address', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: ((user_id is not null) != (api_client_id is not null))
  - constraint: expires_at > created_at
  - constraint: unique(access_token_hash)
  - constraint: selected_server_id is null OR (selected_server_id references servers.id AND servers.organization_id = organization_id)

## Business rules enforced by the tools

- The only exposed tool, 'Optional Settings' (no parameters), maps to retrieving the current authenticated principal's session context (auth_sessions where status='active' and expires_at > now()) and the related organization and accessible servers.
- A session must belong to exactly one principal type: either user_id or api_client_id must be set, but not both.
- A session cannot be created for organizations in status='deleted'; creating sessions for status='suspended' is rejected unless an internal override flag is used (not part of the public tool surface).
- When a session expires (expires_at <= now()), reads must treat it as status='expired' and deny management operations until a new session is created.
- selected_server_id, if set, must reference a server in the same organization as the session.
- Emails are unique per organization; organization slugs are globally unique; server base_url is unique per organization to prevent ambiguous routing.
- Revoking an api_client transitions its status to 'revoked' and requires that all active sessions with api_client_id are transitioned to 'revoked' within the same transaction.