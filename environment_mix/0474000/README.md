# HDW MCP Server — local MCP environment

This backend powers an MCP server that brokers Google and LinkedIn (including Sales Navigator and Messaging/Management) actions on behalf of authenticated tenants. It stores tenant API keys, linked external accounts/sessions, and an auditable log of every tool invocation and its normalized entities (profiles/companies/posts/messages) for caching, deduplication, and compliance.

Repository: https://github.com/horizondatawave/hdw-mcp-server
Homepage: https://smithery.ai/server/@horizondatawave/hdw-mcp-server

## Datastore

- `tenants.json` — Workspaces/tenants that own API keys, quotas, and linked external (LinkedIn/Google) accounts used to execute tools. (18 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_request_limit', 'monthly_request_used', 'monthly_cost_usd_limit', 'monthly_cost_usd_used', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_request_limit >= 0
  - constraint: monthly_request_used >= 0
  - constraint: monthly_request_used <= monthly_request_limit OR monthly_request_limit = 0 (0 means unlimited for enterprise)
- `api_keys.json` — API keys used by clients to access the MCP server; keys are scoped to a tenant and used for quota enforcement and auditing. (18 rows; fields: ['id', 'tenant_id', 'name', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(tenant_id, name)
  - constraint: unique(key_hash)
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
- `external_accounts.json` — Linked external identities/sessions used to execute LinkedIn and Google operations. For LinkedIn tools where 'Account ID is taken from environment', this record represents the configured runtime account per tenant. (19 rows; fields: ['id', 'tenant_id', 'provider', 'status', 'external_account_id', 'display_name', 'auth_type', 'credential_ref', 'scopes', 'expires_at', 'last_verified_at', 'is_default_for_provider', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'reauth_required', 'disabled']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: unique(tenant_id, provider, external_account_id)
  - constraint: at most one is_default_for_provider=true per (tenant_id, provider)
  - constraint: credential_ref length > 0
- `tool_invocations.json` — Immutable audit log of each MCP tool call, including input payload, execution routing (provider account), response summary, caching metadata, and errors. Serves as the backbone for quota metering and debugging. (19 rows; fields: ['id', 'tenant_id', 'api_key_id', 'external_account_id', 'tool_name', 'status', 'request_params', 'request_fingerprint', 'response_payload', 'http_status', 'error_code', 'error_message', 'cache_hit', 'cache_ttl_seconds', 'upstream_latency_ms', 'cost_usd_estimate', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: fk(external_account_id) references external_accounts(id) on delete set null
  - constraint: cache_ttl_seconds >= 0
- `linkedin_entities.json` — Normalized cache of LinkedIn domain objects (profiles, companies, posts, comments, conversations/messages) keyed by URN/id/email where applicable. Populated from read tools and referenced by write tools for validation/targeting. (18 rows; fields: ['id', 'tenant_id', 'entity_type', 'linkedin_urn', 'public_url', 'email', 'display_name', 'company_linkedin_urn', 'raw_payload', 'source_invocation_id', 'status', 'observed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'redacted', 'deleted']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: fk(source_invocation_id) references tool_invocations(id) on delete set null
  - constraint: unique(tenant_id, entity_type, linkedin_urn) WHERE linkedin_urn is not null
  - constraint: unique(tenant_id, entity_type, email) WHERE email is not null AND entity_type = 'user_profile'

## Business rules enforced by the tools

- Every tool call must create a tool_invocations row with status=queued, then transition queued->running->(succeeded|failed) or queued/running->cancelled; no other status transitions are permitted.
- Tools that state 'Account ID is taken from environment' must resolve to external_accounts.is_default_for_provider=true for the matching provider; if none exists or status != active, the invocation must fail with error_code=AUTH_FAILED.
- For any invocation with api_key_id not null: api_keys.status must be active and api_keys.tenant_id must equal tool_invocations.tenant_id, otherwise reject.
- Quota enforcement: before moving an invocation to running, tenants.status must be active and (monthly_request_limit=0 OR monthly_request_used < monthly_request_limit) and (monthly_cost_usd_limit=0 OR monthly_cost_usd_used + cost_usd_estimate <= monthly_cost_usd_limit); otherwise fail with error_code=QUOTA_EXCEEDED.
- On invocation success, increment tenants.monthly_request_used by 1 and tenants.monthly_cost_usd_used by cost_usd_estimate atomically with writing status=succeeded.
- google_search and get_linkedin_google_company responses may be cached via tool_invocations.request_fingerprint for cache_ttl_seconds>0; cached responses must only be served within TTL and only within the same tenant.
- LinkedIn read tools (search_linkedin_users, get_linkedin_profile, get_linkedin_email_user, get_linkedin_user_posts, get_linkedin_user_reactions, get_linkedin_user_connections, get_linkedin_post_reposts, get_linkedin_post_comments, get_linkedin_company, get_linkedin_company_employees, get_linkedin_conversations, get_linkedin_chat_messages) must upsert relevant linkedin_entities with observed_at=now and status=active unless the payload indicates deletion/unavailability (then status=stale).
- LinkedIn write tools (send_linkedin_chat_message, send_linkedin_connection, send_linkedin_post_comment, send_linkedin_post) must create a tool_invocations row and, on success, upsert the created/affected entity (message/post/comment) in linkedin_entities with source_invocation_id set.
- PII controls: if an entity is marked redacted, response_payload returned from cache must omit email and any raw_payload fields flagged as sensitive (enforced in application).
- FK integrity: deleting a tenant must cascade delete api_keys, external_accounts, and linkedin_entities; tool_invocations are retained for audit but must have tenant_id still valid (tenants.status would become deleted instead of hard delete in production).