# ChatGPT Server — local MCP environment

This backend stores configuration and authentication state for a ChatGPT-compatible server integration that allows a user to sign in and manage server connections. The main workflow is: a user creates/updates optional settings, signs in to establish a session, and the system tracks active sessions and related audit history.

Repository: https://github.com/billster45/mcp-chatgpt-responses
Homepage: https://smithery.ai/server/@billster45/mcp-chatgpt-responses

## Datastore

- `accounts.json` — End-user identities that can sign in to manage ChatGPT Server connections and settings. (18 rows; fields: ['id', 'email', 'display_name', 'password_hash', 'auth_provider', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(email)
  - constraint: email must be non-empty and syntactically valid
  - constraint: auth_provider in ('local','oauth','sso')
  - constraint: status in ('active','suspended','deleted')
- `servers.json` — Remote ChatGPT Server endpoints a user can connect to and manage (per environment/instance). (18 rows; fields: ['id', 'name', 'base_url', 'environment', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(base_url)
  - constraint: base_url must be a valid URL and use https except in development/custom environments
  - constraint: environment in ('production','staging','development','custom')
  - constraint: status in ('active','disabled','deleted')
- `optional_settings.json` — Persisted optional settings used by the tool surface 'Optional Settings' to manage sign-in and server access behavior per account and server. (18 rows; fields: ['id', 'account_id', 'server_id', 'default_model', 'request_timeout_ms', 'max_retries', 'verify_tls', 'store_tokens', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(account_id, server_id)
  - constraint: fk(account_id) references accounts(id) on delete cascade
  - constraint: fk(server_id) references servers(id) on delete cascade
  - constraint: request_timeout_ms between 1000 and 300000
- `auth_sessions.json` — Sign-in sessions established for an account to access/manage a specific server. Stores token metadata needed for authenticated API access. (19 rows; fields: ['id', 'account_id', 'server_id', 'optional_settings_id', 'access_token_ciphertext', 'refresh_token_ciphertext', 'token_type', 'scopes', 'expires_at', 'last_used_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: fk(account_id) references accounts(id) on delete cascade
  - constraint: fk(server_id) references servers(id) on delete cascade
  - constraint: fk(optional_settings_id) references optional_settings(id) on delete set null
  - constraint: unique(account_id, server_id, status) where status='active' (at most one active session per account+server)
- `audit_events.json` — Append-only audit log for sign-in and settings management actions used for security and supportability. (19 rows; fields: ['id', 'account_id', 'server_id', 'session_id', 'event_type', 'ip_address', 'user_agent', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['settings.created', 'settings.updated', 'settings.disabled', 'settings.enabled', 'auth.sign_in_succeeded', 'auth.sign_in_failed', 'auth.token_refreshed', 'auth.session_revoked']
  - constraint: append-only: no update except updated_at normalization; no delete except via retention policy
  - constraint: fk(account_id) references accounts(id) on delete set null
  - constraint: fk(server_id) references servers(id) on delete set null
  - constraint: fk(session_id) references auth_sessions(id) on delete set null

## Business rules enforced by the tools

- The 'Optional Settings' tool must read/write only optional_settings rows; because the tool surface has no parameters, the implementation must resolve account_id from the authenticated caller context and server_id from a configured default server or the caller context.
- When optional_settings.store_tokens is false, auth_sessions.access_token_ciphertext and refresh_token_ciphertext must be null; when store_tokens is true, they may be populated.
- A sign-in action must create an auth_sessions row with status='active' and must revoke (set status='revoked') any prior active session for the same (account_id, server_id) within the same transaction.
- Account status='suspended' or 'deleted' prohibits creating new auth_sessions and prohibits enabling optional_settings.
- Server status='disabled' or 'deleted' prohibits creating new auth_sessions and prohibits enabling optional_settings for that server.
- Token refresh may only occur for auth_sessions.status='active' and must update expires_at, last_used_at, and write an audit_events row of type 'auth.token_refreshed'.
- Every create/update/enable/disable of optional_settings must write a corresponding audit_events row capturing changed fields in metadata.changed_fields.
- request_timeout_ms and max_retries must be enforced on every outgoing request made using the settings; if out of range, settings changes must be rejected.
- Uniqueness constraints must be enforced: accounts.email unique; servers.base_url unique; optional_settings unique(account_id, server_id); at most one active auth session per (account_id, server_id).