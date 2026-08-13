# Query | MCP Server for Supabase — local MCP environment

This backend stores Supabase MCP server connection profiles and authenticated sessions used to access and manage Supabase projects through a signed-in server identity. The main workflow is creating/maintaining server records, exchanging credentials for sessions, and enforcing access controls/auditability for all actions performed via those sessions.

Repository: https://github.com/alexander-zuev/supabase-mcp-server
Homepage: https://smithery.ai/server/@alexander-zuev/supabase-mcp-server

## Datastore

- `mcp_servers.json` — Registered MCP server instances (or profiles) that can be signed into to access Supabase on behalf of a user or service account. (12 rows; fields: ['id', 'name', 'base_url', 'environment', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(name, environment)
  - constraint: base_url <> ''
  - constraint: name <> ''
- `auth_identities.json` — Identities used to sign in to Supabase (e.g., personal access token, OAuth, service role key). Secrets are stored as encrypted blobs and never returned in plaintext. (12 rows; fields: ['id', 'server_id', 'provider', 'account_label', 'secret_ciphertext', 'secret_kid', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'deleted']
  - constraint: fk(server_id) references mcp_servers(id) on delete restrict
  - constraint: secret_ciphertext <> ''
  - constraint: secret_kid <> ''
  - constraint: unique(server_id, provider, account_label)
- `auth_sessions.json` — Issued sign-in sessions for a given identity, used by the MCP server to perform authenticated calls to Supabase. (21 rows; fields: ['id', 'server_id', 'identity_id', 'access_token_ciphertext', 'refresh_token_ciphertext', 'expires_at', 'status', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked', 'error']
  - constraint: fk(server_id) references mcp_servers(id) on delete restrict
  - constraint: fk(identity_id) references auth_identities(id) on delete restrict
  - constraint: expires_at is null OR expires_at > created_at
- `supabase_projects.json` — Supabase project references that become available to the MCP server after sign-in; used to scope future management actions. (25 rows; fields: ['id', 'server_id', 'supabase_project_ref', 'display_name', 'organization_id', 'region', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: fk(server_id) references mcp_servers(id) on delete restrict
  - constraint: supabase_project_ref <> ''
  - constraint: unique(server_id, supabase_project_ref)
- `audit_events.json` — Immutable audit log of sign-in attempts and server management actions invoked through the MCP server. (34 rows; fields: ['id', 'server_id', 'identity_id', 'session_id', 'event_type', 'success', 'ip_address', 'user_agent', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['server.created', 'server.updated', 'server.disabled', 'server.deleted', 'auth.signin.started', 'auth.signin.succeeded', 'auth.signin.failed', 'auth.session.refreshed', 'auth.session.revoked', 'projects.synced']
  - constraint: fk(server_id) references mcp_servers(id) on delete restrict
  - constraint: fk(identity_id) references auth_identities(id) on delete set null
  - constraint: fk(session_id) references auth_sessions(id) on delete set null
  - constraint: updated_at = created_at

## Business rules enforced by the tools

- The only exposed tool ("Optional Settings") has an empty parameter schema; therefore any server selection/sign-in context must be derived from stored defaults (e.g., most recently active server/session) rather than tool arguments.
- A server with status=deleted cannot create new identities or sessions.
- An identity with status in (revoked, deleted) cannot be used to create new sessions.
- At most one active session per (server_id, identity_id) may exist at a time; creating a new active session must revoke or expire the previous active session.
- Secrets (secret_ciphertext, access_token_ciphertext, refresh_token_ciphertext) must never be written to audit_events.metadata in plaintext; only redacted fingerprints/last4 hashes are allowed.
- When expires_at is non-null and is in the past, auth_sessions.status must be transitioned to expired on read/refresh attempts.
- Disabling a server (mcp_servers.status=disabled) must revoke all active sessions for that server.
- Deleting a server (mcp_servers.status=deleted) is a soft-delete; rows remain for auditability but no new sessions may be created and no project sync may be performed.
- supabase_projects rows may only be inserted/updated by a successful authenticated session and must be unique per (server_id, supabase_project_ref).