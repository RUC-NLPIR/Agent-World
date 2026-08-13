# Inbox MCP — local MCP environment

This backend stores user accounts and their authenticated sessions for signing in and managing access to Inbox MCP servers. The main workflows are creating a user identity, issuing/revoking sessions, and registering/managing servers that a signed-in user can access.

Repository: https://github.com/darinkishore/Inbox-MCP
Homepage: https://smithery.ai/server/@darinkishore/inbox-mcp

## Datastore

- `users.json` — Human user identities that can sign in to manage Inbox MCP servers. (18 rows; fields: ['id', 'email', 'display_name', 'password_hash', 'auth_provider', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(email)
  - constraint: email must be lowercase and RFC5322-like
  - constraint: if auth_provider = 'local' then password_hash is not null
  - constraint: if status = 'deleted' then email is retained but user cannot authenticate
- `sessions.json` — Authenticated sessions issued after sign-in; used to access and manage servers. (18 rows; fields: ['id', 'user_id', 'access_token_hash', 'refresh_token_hash', 'status', 'issued_at', 'expires_at', 'last_seen_at', 'ip_address', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: foreign key (user_id) references users(id) on delete restrict
  - constraint: unique(access_token_hash)
  - constraint: expires_at > issued_at
  - constraint: if status in ('revoked','expired') then it cannot transition back to 'active'
- `servers.json` — Inbox MCP servers that can be managed and accessed by signed-in users. (18 rows; fields: ['id', 'owner_user_id', 'name', 'base_url', 'environment', 'status', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: foreign key (owner_user_id) references users(id) on delete restrict
  - constraint: unique(owner_user_id, name)
  - constraint: base_url must be a valid http(s) URL
  - constraint: if status = 'deleted' then server is not returned in default listings
- `server_access.json` — Join table granting users roles/permissions on servers (for shared management). (18 rows; fields: ['id', 'server_id', 'user_id', 'role', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (server_id) references servers(id) on delete cascade
  - constraint: foreign key (user_id) references users(id) on delete restrict
  - constraint: unique(server_id, user_id)
  - constraint: exactly one active 'owner' role per server_id

## Business rules enforced by the tools

- The 'Optional Settings' tool performs sign-in/sign-out and server access management actions only; because its parameter schema has no properties, all inputs must be derived from the caller's authenticated context (e.g., existing bearer token) and/or defaults.
- A request without a valid active session (sessions.status='active' and sessions.expires_at > now) must be treated as unauthenticated and cannot list or modify servers beyond public/default configuration (if any).
- On successful sign-in, create a sessions row with status='active', unique access_token_hash, issued_at=now, expires_at=now+TTL; update users.last_login_at.
- On sign-out, transition the session from 'active' to 'revoked'; revoked sessions cannot be reactivated.
- A user with users.status != 'active' cannot receive an active session.
- Server creation requires an active session; create servers row with status='active' and create server_access row granting role='owner' status='active' to the creating user.
- Only users with an active access grant (server_access.status='active') can manage a server; role-based permissions must be enforced: owner/admin can edit and grant access, editor can edit server metadata, viewer can only read.
- Deleting a server transitions servers.status to 'deleted' and revokes all active server_access grants for that server.
- Uniqueness constraints must be enforced transactionally: unique(users.email), unique(servers.owner_user_id, servers.name), unique(server_access.server_id, server_access.user_id).