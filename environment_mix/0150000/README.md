# 1Password Credential Retrieval Server — local MCP environment

This backend powers a minimal credential retrieval service that returns 1Password-stored secrets to authorized callers. It tracks API clients, their access policies, audit logs of retrievals, and cached retrieval sessions to avoid repeated calls to the 1Password CLI/connect layer while preserving least-privilege and traceability.

Repository: https://github.com/dkvdm/onepassword-mcp-server
Homepage: https://smithery.ai/server/@dkvdm/onepassword-mcp-server

## Datastore

- `api_clients.json` — Registered callers of the credential retrieval server (service accounts, apps, users) authenticated via an API key or token. (12 rows; fields: ['id', 'name', 'api_key_hash', 'key_prefix', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(name)
  - constraint: unique(key_prefix)
  - constraint: api_key_hash length >= 32
  - constraint: key_prefix length between 6 and 16
- `credential_policies.json` — Allow/deny rules mapping API clients to which 1Password items/vaults they may retrieve and which fields are permitted (e.g., password only). (26 rows; fields: ['id', 'client_id', 'vault_id', 'item_id', 'item_title_match', 'allowed_fields', 'effect', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: foreign key (client_id) references api_clients(id) on delete cascade
  - constraint: at least one of (vault_id, item_id, item_title_match) must be non-null
  - constraint: if item_id is non-null then vault_id may be null or non-null (implementation chooses lookup method)
  - constraint: allowed_fields must be non-empty
- `retrieval_sessions.json` — Short-lived server-side sessions representing a successful authenticated and authorized retrieval attempt; used for caching and rate limiting without storing secrets. (32 rows; fields: ['id', 'client_id', 'request_fingerprint', 'status', 'expires_at', 'last_accessed_at', 'failure_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked', 'failed']
  - constraint: foreign key (client_id) references api_clients(id) on delete cascade
  - constraint: expires_at > created_at
  - constraint: unique(client_id, request_fingerprint, status) where status='active'
- `retrieval_audit_logs.json` — Immutable audit trail of each call to get_1password_credentials, including authorization decision and which 1Password references were accessed (never store returned secrets). (36 rows; fields: ['id', 'client_id', 'session_id', 'request_id', 'source_ip', 'user_agent', 'op_vault_id', 'op_item_id', 'op_item_title', 'allowed_fields_effective', 'decision', 'http_status', 'error_code', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `decision`: ['allowed', 'denied', 'error']
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
  - constraint: foreign key (session_id) references retrieval_sessions(id) on delete set null
  - constraint: unique(request_id)
  - constraint: http_status between 100 and 599 when not null

## Business rules enforced by the tools

- get_1password_credentials must authenticate the caller to exactly one api_clients row with status='active' by comparing a presented secret to api_clients.api_key_hash (constant-time compare).
- For every get_1password_credentials call, the system must insert exactly one retrieval_audit_logs row with a unique request_id, even when the call is denied or errors.
- A call is allowed only if there exists at least one credential_policies row with client_id matching the caller, status='active', effect='allow', and whose (vault_id/item_id/item_title_match) matches the requested 1Password lookup; and there exists no matching active effect='deny' policy (deny overrides allow).
- The server must never persist returned secret material (passwords, TOTP codes, private keys). Only references (vault/item identifiers, title) and permitted field names may be stored in retrieval_audit_logs.
- If a retrieval_session is created, it must start in status='active' and have expires_at within a configured TTL window (e.g., <= 24 hours from created_at); after expires_at it may only transition to 'expired'.
- If api_clients.status transitions to 'revoked', all active retrieval_sessions for that client must transition to 'revoked' within the same transaction or via guaranteed asynchronous job.
- Rate limiting/quota (implementation-defined) must be enforced per client; on quota violation the decision must be 'denied' and http_status must be 429 in retrieval_audit_logs.
- credential_policies.allowed_fields_effective returned to the caller must be the intersection of requested fields (if any) and policy.allowed_fields; if no fields remain, the request is denied and audited.