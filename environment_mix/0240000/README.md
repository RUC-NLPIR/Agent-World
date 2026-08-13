# Self-Hosted Supabase MCP Server — local MCP environment

This backend stores configuration and access control for a self-hosted Supabase MCP server, centered around authenticating an operator and managing registered Supabase-backed servers. The primary workflow is: an operator signs in, receives a session, and then uses that session to view/manage server connection settings and access policies.

Repository: https://github.com/HenkDz/selfhosted-supabase-mcp
Homepage: https://smithery.ai/server/@HenkDz/selfhosted-supabase-mcp

## Datastore

- `operators.json` — Human operators/admin users who can sign into the self-hosted MCP server to manage registered Supabase servers and settings. (12 rows; fields: ['id', 'email', 'password_hash', 'display_name', 'role', 'status', 'last_login_at', 'failed_login_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'locked']
  - constraint: unique(email)
  - constraint: failed_login_count >= 0
  - constraint: role in ('owner','admin','viewer')
  - constraint: status in ('active','disabled','locked')
- `sessions.json` — Authenticated sessions created when an operator signs in; used to authorize subsequent server management actions. (20 rows; fields: ['id', 'operator_id', 'session_token_hash', 'status', 'issued_at', 'expires_at', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: unique(session_token_hash)
  - constraint: expires_at > issued_at
  - constraint: status in ('active','revoked','expired')
  - constraint: foreign key(operator_id) references operators(id) on delete cascade
- `supabase_servers.json` — Registered Supabase instances (self-hosted or cloud) that the MCP server can connect to on behalf of an authenticated operator. (12 rows; fields: ['id', 'name', 'base_url', 'project_ref', 'owner_operator_id', 'status', 'notes', 'last_healthcheck_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(owner_operator_id, name)
  - constraint: base_url like 'http%'
  - constraint: status in ('active','disabled','deleted')
  - constraint: foreign key(owner_operator_id) references operators(id)
- `server_credentials.json` — Encrypted credentials/config needed to connect to a specific Supabase server (kept separate from the server record for security and rotation). (18 rows; fields: ['id', 'server_id', 'credential_type', 'secret_ciphertext', 'secret_kid', 'status', 'last_rotated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'rotated', 'revoked']
  - constraint: unique(server_id, credential_type, status) where status = 'active'
  - constraint: status in ('active','rotated','revoked')
  - constraint: foreign key(server_id) references supabase_servers(id) on delete cascade

## Business rules enforced by the tools

- The tool "Optional Settings" (sign-in / manage servers) must create a session row with status='active' only if the operator exists, status='active', and the provided password verifies against operators.password_hash.
- On each failed sign-in attempt, operators.failed_login_count increments by 1; if failed_login_count reaches 10, operators.status transitions to 'locked' and no new sessions may be issued until unlocked by an admin/owner.
- A session is valid only when sessions.status='active' and now() < sessions.expires_at; otherwise it must be treated as expired and may be transitioned to status='expired'.
- Only operators with role in ('owner','admin') may create/update/disable/delete supabase_servers entries; role='viewer' is read-only.
- supabase_servers.name must be unique per owner_operator_id; renaming must enforce the same uniqueness constraint.
- Credentials may never be stored in plaintext; server_credentials.secret_ciphertext must be non-empty and created using secret_kid; retrieving secrets must only return redacted metadata (type/status/rotation timestamps) unless an internal privileged path is used.
- At most one active credential per (server_id, credential_type) may exist at any time; rotating a credential must mark the previous active credential as 'rotated' before inserting a new 'active' one.
- Deleting a server must transition supabase_servers.status to 'deleted' and cascade-delete or revoke associated sessions/credentials according to policy; at minimum, server_credentials for that server must not remain 'active'.