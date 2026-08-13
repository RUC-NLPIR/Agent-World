# Zendesk Integration Server — local MCP environment

This backend powers a Zendesk Integration Server that brokers access to Zendesk tickets, comments, and incident links for multiple workspaces/accounts while enforcing auth, auditability, and rate limits. Core workflows include creating/updating tickets, appending public/private comments, fetching ticket details with comments, searching tickets, and retrieving linked incidents via problem/incident relationships.

Repository: https://github.com/koundinya/zd-mcp-server
Homepage: https://smithery.ai/server/@koundinya/zd-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace configuration for connecting to a specific Zendesk account/subdomain, including operational status and basic limits. (12 rows; fields: ['id', 'name', 'zendesk_subdomain', 'default_locale', 'status', 'daily_request_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(zendesk_subdomain)
  - constraint: daily_request_quota >= 0
- `api_keys.json` — API keys used by clients of the integration server; ties requests to a workspace and enforces per-key quotas. Stores a hash of the secret rather than the secret itself. (13 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'requests_per_minute', 'daily_request_quota', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_prefix)
  - constraint: requests_per_minute >= 1 and requests_per_minute <= 600
  - constraint: daily_request_quota >= 0
- `zendesk_connections.json` — Stores per-workspace Zendesk authentication and settings required to call the Zendesk API. Secrets are stored encrypted and rotated with explicit status. (12 rows; fields: ['id', 'workspace_id', 'auth_type', 'zendesk_email', 'encrypted_api_token', 'encrypted_oauth_access_token', 'oauth_refresh_token', 'oauth_token_expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'invalid', 'rotating', 'disabled']
  - constraint: unique(workspace_id)
  - constraint: if auth_type = 'api_token' then zendesk_email is not null and encrypted_api_token is not null
  - constraint: if auth_type = 'oauth' then encrypted_oauth_access_token is not null
- `tickets.json` — Locally cached representation of Zendesk tickets for search and detail retrieval; updated on reads/writes via Zendesk API. Not a full mirror, but enough to serve tools and maintain linkage and comment indexing. (20 rows; fields: ['id', 'workspace_id', 'zendesk_ticket_id', 'subject', 'description', 'priority', 'type', 'status', 'requester_id', 'assignee_id', 'group_id', 'tags', 'custom_fields', 'problem_zendesk_ticket_id', 'zendesk_created_at', 'zendesk_updated_at', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['new', 'open', 'pending', 'hold', 'solved', 'closed', 'deleted']
  - constraint: unique(workspace_id, zendesk_ticket_id)
  - constraint: zendesk_ticket_id > 0
- `ticket_comments.json` — Ticket comments/notes (public and private) cached for detailed retrieval and for enriching search. Appends are created when adding notes; periodic refresh may backfill from Zendesk. (18 rows; fields: ['id', 'workspace_id', 'ticket_id', 'zendesk_ticket_id', 'zendesk_comment_id', 'visibility', 'author_zendesk_user_id', 'body', 'via', 'is_from_integration', 'zendesk_created_at', 'created_at', 'updated_at'])
  - lifecycle `visibility`: ['public', 'private']
  - constraint: zendesk_ticket_id > 0
  - constraint: if zendesk_comment_id is not null then unique(workspace_id, zendesk_comment_id)
  - constraint: body <> ''
  - constraint: FK(ticket_id) must reference tickets.id with same workspace_id
- `ticket_links.json` — Models Zendesk problem/incident relationships to support fetching linked incidents for a given ticket. Populated from Zendesk fields like problem_id and/or through ticket type relationships. (18 rows; fields: ['id', 'workspace_id', 'problem_ticket_id', 'incident_ticket_id', 'problem_zendesk_ticket_id', 'incident_zendesk_ticket_id', 'link_type', 'status', 'last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: problem_zendesk_ticket_id > 0
  - constraint: incident_zendesk_ticket_id > 0
  - constraint: problem_ticket_id <> incident_ticket_id
  - constraint: unique(workspace_id, link_type, problem_zendesk_ticket_id, incident_zendesk_ticket_id)

## Business rules enforced by the tools

- Every request must authenticate via an active api_keys row; api_keys.status must be 'active' and the owning workspaces.status must be 'active'.
- A workspace must have exactly one zendesk_connections row; it must be in status 'active' to perform any Zendesk read/write tool.
- Quota enforcement: For each api_keys.id, requests must not exceed requests_per_minute and daily_request_quota; additionally, aggregate requests across a workspace must not exceed workspaces.daily_request_quota.
- zendesk_create_ticket: must create a tickets row with a unique (workspace_id, zendesk_ticket_id) after Zendesk returns the id; initial status must be one of ['new','open','pending','hold'] (never 'deleted').
- zendesk_get_ticket: must upsert tickets by (workspace_id, zendesk_ticket_id) from Zendesk; set last_synced_at and zendesk_updated_at.
- zendesk_update_ticket: must only apply status transitions allowed by tickets.lifecycle.transitions; if Zendesk rejects a transition, the local cache must not advance status.
- zendesk_add_private_note and zendesk_add_public_note: must append a ticket_comments row with visibility matching the tool; body must be non-empty; on success, update tickets.zendesk_updated_at and last_synced_at.
- zendesk_get_ticket_details: must return the ticket plus ordered ticket_comments for the ticket; if comments are missing/stale, it may refresh from Zendesk and upsert by (workspace_id, zendesk_comment_id) when available.
- zendesk_search: must search over tickets.subject/description/tags and optionally ticket_comments.body; results must be limited by a server-side maximum (e.g., <= 100) even if client asks for more.
- zendesk_get_linked_incidents: for a given problem ticket (type='problem' or any ticket with linked incidents), return incident tickets through ticket_links where link_type='problem_incident' and status='active'; links must be refreshed from Zendesk when last_verified_at is older than a configured TTL.
- FK integrity rule: ticket_comments.ticket_id and ticket_links.*_ticket_id must reference tickets within the same workspace_id; cross-workspace linking is forbidden.
- Soft-delete handling: if Zendesk indicates a ticket is deleted/unavailable, mark tickets.status='deleted' and prevent new comments from being added through this service.