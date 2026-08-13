# Databricks MCP Server — local MCP environment

This backend stores authentication state and configuration for connecting an MCP server to Databricks workspaces. The primary workflow is a user (or operator) creating and managing one or more Databricks server/workspace connections via sign-in, maintaining session state and auditability.

Repository: https://github.com/JustTryAI/databricks-mcp-server
Homepage: https://smithery.ai/server/@JustTryAI/databricks-mcp-server

## Datastore

- `accounts.json` — Represents a human user or operator who can sign in and manage Databricks server connections. (18 rows; fields: ['id', 'email', 'display_name', 'role', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(email)
  - constraint: email must be a valid email format
  - constraint: role in ('owner','admin','member','viewer')
  - constraint: status in ('active','suspended','deleted')
- `databricks_connections.json` — Stores Databricks server/workspace connection settings that can be managed after sign-in (host, workspace identifiers, and authentication method metadata). Secrets are not stored directly here; they are referenced via secret_ref. (18 rows; fields: ['id', 'account_id', 'name', 'databricks_host', 'cloud', 'workspace_id', 'auth_type', 'secret_ref', 'is_default', 'status', 'last_validated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(account_id, name)
  - constraint: databricks_host must be a valid URL
  - constraint: auth_type in ('pat','oauth','azure_sp','gcp_sa','instance_profile','none')
  - constraint: status in ('active','disabled','deleted')
- `auth_sessions.json` — Tracks sign-in sessions used by the MCP server to access and manage Databricks connections, including expiration and revocation. Supports the 'Access and manage servers by signing in' workflow. (19 rows; fields: ['id', 'account_id', 'connection_id', 'session_token_hash', 'issued_at', 'expires_at', 'revoked_at', 'client_metadata', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: unique(session_token_hash)
  - constraint: expires_at > issued_at
  - constraint: status in ('active','expired','revoked')
  - constraint: revoked_at is not null implies status='revoked'
- `api_keys.json` — API keys used by clients to call the MCP server endpoints that implement 'Optional Settings' and related management actions. Keys can be scoped to an account and optionally to a specific Databricks connection. (18 rows; fields: ['id', 'account_id', 'connection_id', 'name', 'key_prefix', 'key_hash', 'scopes', 'last_used_at', 'expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(account_id, name)
  - constraint: status in ('active','revoked')
  - constraint: expires_at is null OR expires_at > created_at

## Business rules enforced by the tools

- The 'Optional Settings' tool performs authenticated access; a request must authenticate via either a valid active auth_sessions.session_token_hash match or an active api_keys.key_hash match.
- An account with status='suspended' or 'deleted' cannot create new sessions, create/update connections, or create new API keys.
- A databricks_connections row with status!='active' cannot be selected as auth_sessions.connection_id for a new session.
- For each account_id, there can be at most one active databricks_connections row where is_default=true; setting one connection as default must unset any other default in the same account within the same transaction.
- Secret material (PAT, OAuth refresh token, service principal secret) must never be stored in plaintext in any collection; only secret_ref or hashes are allowed.
- Revoking a session sets status='revoked' and revoked_at=now(); a revoked session cannot transition back to active.
- API keys are immutable in value: rotating a key creates a new api_keys row and revokes the old one.
- Deleting a connection (status='deleted') is a soft delete; it must not break FK integrity—existing sessions referencing it must either be revoked or connection_id set to null during the same maintenance operation.