# Supabase MCP Server — local MCP environment

This backend stores Supabase MCP Server sign-in configuration and the set of reachable Supabase "servers" (projects/environments) a user can manage after authentication. The primary workflow is: configure optional settings, authenticate, register accessible Supabase projects, and keep an audit trail of configuration and access.

Repository: https://github.com/Anthony9906/supabase-mcp-server
Homepage: https://smithery.ai/server/@Anthony9906/supabase-mcp-server

## Datastore

- `mcp_settings.json` — Persisted optional settings/config used by the MCP server runtime, including auth mode and connection defaults. This collection exists to back the 'Optional Settings' tool, even though the current surface shows no parameters. (12 rows; fields: ['id', 'scope', 'user_id', 'auth_mode', 'default_server_id', 'redact_secrets_in_logs', 'request_timeout_ms', 'max_concurrent_requests', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(scope, user_id) where scope='user'
  - constraint: unique(scope) where scope='global'
  - constraint: request_timeout_ms >= 1000 and request_timeout_ms <= 120000
  - constraint: max_concurrent_requests >= 1 and max_concurrent_requests <= 200
- `users.json` — Identities that can sign into the MCP server and manage Supabase servers/projects. This is the principal for scoping settings and stored credentials. (12 rows; fields: ['id', 'email', 'display_name', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(email) where email is not null
- `supabase_servers.json` — Supabase targets (projects/environments) that the MCP server can manage after sign-in. Represents the reachable upstream endpoints and metadata needed for routing calls. (12 rows; fields: ['id', 'owner_user_id', 'supabase_project_ref', 'name', 'api_base_url', 'region', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['linked', 'disabled', 'revoked']
  - constraint: unique(owner_user_id, supabase_project_ref)
  - constraint: api_base_url like 'https://%'
- `auth_sessions.json` — Sign-in sessions for the MCP server. Tracks whether a user is currently authenticated and which credential was used. (12 rows; fields: ['id', 'user_id', 'credential_id', 'issued_at', 'expires_at', 'revoked_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: expires_at is null or expires_at > issued_at
  - constraint: revoked_at is null or revoked_at >= issued_at
  - constraint: not (status='active' and revoked_at is not null)
- `credentials.json` — Stored upstream authentication material used to access Supabase (PATs or OAuth tokens). Secrets are stored encrypted/hashed; plaintext is never persisted. (14 rows; fields: ['id', 'user_id', 'type', 'label', 'secret_ciphertext', 'secret_fingerprint', 'expires_at', 'last_used_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'rotated', 'revoked']
  - constraint: unique(user_id, secret_fingerprint)
  - constraint: expires_at is null or expires_at > created_at

## Business rules enforced by the tools

- The 'Optional Settings' tool must read and/or upsert exactly one active settings row per scope: one row where scope='global' (user_id null) and at most one row per user where scope='user' (user_id not null).
- If mcp_settings.auth_mode='none', then no active credentials may be required for operation and auth_sessions.credential_id may be null; if auth_mode in ('pat','oauth'), at least one active credential of a compatible type must exist for the acting user before creating an active session.
- A supabase_servers row may only be created/linked by an active user, and must have a unique (owner_user_id, supabase_project_ref).
- When a credential status becomes 'revoked', all active auth_sessions referencing that credential must transition to 'revoked' within the same transaction.
- auth_sessions.status='active' is only valid if (revoked_at is null) and (expires_at is null or expires_at > now()). If expires_at <= now(), the session must be transitioned to 'expired'.
- mcp_settings.default_server_id, if set, must reference a supabase_servers row owned by the same user when scope='user'; for scope='global', it must reference a server visible to the system (enforced by application policy).
- Secret material must never be stored in plaintext: credentials.secret_ciphertext must be produced by an approved envelope encryption scheme and credentials.secret_fingerprint must be derived using an HMAC with a server-held key.