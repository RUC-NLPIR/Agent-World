# Freshdesk Integration Server — local MCP environment

This backend models a Freshdesk Integration Server that proxies Freshdesk objects (tickets, contacts, agents, companies, groups, canned responses, solutions) and keeps a local, queryable cache for search/list/view operations. It also stores per-tenant Freshdesk connection credentials and tracks sync state/lifecycle so the API can serve reads quickly while keeping data consistent with Freshdesk.

Repository: https://github.com/effytech/freshdesk_mcp
Homepage: https://smithery.ai/server/@effytech/freshdesk_mcp

## Datastore

- `tenants.json` — Represents a connected Freshdesk account (a customer/tenant) plus its authentication material and operational settings used by the integration server. (12 rows; fields: ['id', 'status', 'name', 'freshdesk_domain', 'freshdesk_api_base_url', 'auth_type', 'api_key_ciphertext', 'oauth_access_token_ciphertext', 'oauth_refresh_token_ciphertext', 'oauth_token_expires_at', 'default_page_size', 'rate_limit_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(freshdesk_domain)
  - constraint: default_page_size between 1 and 100
  - constraint: rate_limit_per_minute between 1 and 600
  - constraint: auth_type = 'api_key' implies api_key_ciphertext is not null
- `people_and_orgs.json` — Local cache of Freshdesk people/org entities: agents, contacts, companies, and groups. Used to serve list/view/search operations without re-fetching upstream for every request. (37 rows; fields: ['id', 'tenant_id', 'entity_type', 'status', 'freshdesk_id', 'name', 'email', 'phone', 'company_freshdesk_id', 'is_active', 'raw', 'search_text', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(tenant_id, entity_type, freshdesk_id)
  - constraint: freshdesk_id > 0
  - constraint: entity_type in ('agent','contact','company','group')
  - constraint: entity_type in ('agent','contact') implies email may be null but if present must be unique-ish per tenant via partial unique index unique(tenant_id, entity_type, lower(email)) where email is not null and status='active'
- `tickets.json` — Local cache and state for Freshdesk tickets, including custom fields and searchable metadata. Serves get/list/search/create/update/delete ticket operations and links to conversations. (34 rows; fields: ['id', 'tenant_id', 'status', 'freshdesk_id', 'subject', 'description_text', 'priority', 'source', 'type', 'group_freshdesk_id', 'agent_freshdesk_id', 'requester_contact_freshdesk_id', 'company_freshdesk_id', 'tags', 'custom_fields', 'raw', 'search_text', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'pending', 'resolved', 'closed', 'deleted']
  - constraint: unique(tenant_id, freshdesk_id) where freshdesk_id is not null
  - constraint: freshdesk_id is null only for locally-staged create operations and must become non-null when upstream create succeeds
  - constraint: priority between 1 and 4 when not null
  - constraint: source >= 1 when not null
- `ticket_conversations.json` — Conversations, replies, and notes attached to tickets. Supports listing, viewing, creating replies/notes, and updating existing conversations where permitted. (43 rows; fields: ['id', 'tenant_id', 'ticket_id', 'status', 'freshdesk_id', 'conversation_type', 'body_html', 'body_text', 'private', 'author_freshdesk_id', 'raw', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(tenant_id, ticket_id, freshdesk_id) where freshdesk_id is not null
  - constraint: conversation_type in ('reply','note','forward','system')
  - constraint: conversation_type='note' implies private is not null
  - constraint: freshdesk_id > 0 when not null
- `knowledge_and_templates.json` — Stores canned responses and solution knowledge base structures (categories, folders, articles) with minimal normalized fields and raw payloads to support list/view/create/update tools. (39 rows; fields: ['id', 'tenant_id', 'record_type', 'status', 'freshdesk_id', 'parent_freshdesk_id', 'name', 'title', 'content_html', 'raw', 'search_text', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'draft', 'archived', 'deleted']
  - constraint: unique(tenant_id, record_type, freshdesk_id) where freshdesk_id is not null
  - constraint: record_type in ('canned_response','canned_folder','solution_category','solution_folder','solution_article')
  - constraint: freshdesk_id > 0 when not null
  - constraint: record_type in ('canned_response','canned_folder','solution_folder','solution_article') implies parent_freshdesk_id may be required by upstream API; enforce not null for create unless record_type='solution_category'
- `custom_fields.json` — Definitions for dynamic/custom fields for tickets, contacts, and companies, including property metadata used by get_field_properties and list/view/create/update field tools. (41 rows; fields: ['id', 'tenant_id', 'field_scope', 'status', 'freshdesk_id', 'name', 'label', 'field_type', 'required', 'properties', 'position', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(tenant_id, field_scope, name)
  - constraint: unique(tenant_id, field_scope, freshdesk_id) where freshdesk_id is not null
  - constraint: freshdesk_id > 0 when not null
  - constraint: field_scope in ('ticket','contact','company')

## Business rules enforced by the tools

- All tools operate in the context of exactly one tenant; the caller must be mapped to tenants.id (e.g., via server config or API key), and every read/write must filter by tenant_id.
- For get_tickets/list_contacts/get_agents/list_companies/list_groups and all list_* tools, default behavior excludes rows where status='deleted'.
- search_tickets/search_contacts/search_agents/search_companies must search against denormalized search_text and/or raw JSON fields, always filtered by tenant_id and status!='deleted'.
- create_* tools create a local row first with freshdesk_id=null and raw containing the request payload; after upstream Freshdesk succeeds, freshdesk_id and raw are replaced/merged with upstream response and last_synced_at is set.
- update_* tools require the target row to exist for the tenant; if freshdesk_id is null, the update must fail (cannot update upstream object that does not exist). On success, updated_at and last_synced_at must advance and raw must be refreshed.
- delete_ticket must soft-delete locally by setting tickets.status='deleted' and must also attempt upstream delete; if upstream delete fails with not-found, local delete may still succeed but must be recorded by setting last_synced_at and keeping raw intact.
- get_ticket_conversation must only return conversations whose ticket_id belongs to the same tenant; FK integrity is enforced by ticket_conversations.ticket_id referencing tickets.id and ticket_conversations.tenant_id matching tickets.tenant_id.
- create_ticket_reply/create_ticket_note must create ticket_conversations rows with conversation_type='reply' or 'note' respectively; notes must set private to true/false explicitly.
- get_ticket_fields/list_contact_fields/list_company_fields must return custom_fields filtered by field_scope and tenant_id, excluding status='deleted'.
- create_ticket_field/create_contact_field/update_*_field operations must enforce unique(tenant_id, field_scope, name); attempts to create a duplicate name must fail.
- get_field_properties must look up custom_fields by (tenant_id, field_scope inferred from caller route/tool, name) and return custom_fields.properties; if not found locally, the server may fetch from Freshdesk and upsert with last_synced_at.
- view_* tools (view_agent, view_group, view_company, view_solution_article, etc.) must return the cached object by freshdesk_id when present, otherwise fetch upstream and upsert into the corresponding collection.
- list_solution_* and canned response tools must store results into knowledge_and_templates with correct record_type and ensure unique(tenant_id, record_type, freshdesk_id).
- Status transitions declared in lifecycle sections must be enforced; e.g., a deleted record cannot be reactivated, and ticket status must remain within the allowed transition graph.