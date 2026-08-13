# Freshservice Integration Server — local MCP environment

This backend models a multi-tenant Freshservice integration server that mirrors core Freshservice objects (tickets, users/agents/groups, catalog items, and knowledge base). It stores local replicas plus an event/audit log so the server can implement list/get/filter/create/update/delete tools and track lifecycle/state transitions consistent with Freshservice.

Repository: https://github.com/effytech/freshservice_mcp
Homepage: https://smithery.ai/server/@effytech/freshservice_mcp

## Datastore

- `fs_accounts.json` — Tenant/account connection to a specific Freshservice domain. All synced objects belong to an account; tool calls resolve to exactly one account context. (12 rows; fields: ['id', 'freshservice_domain', 'api_key_hash', 'default_workspace_id', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(freshservice_domain)
  - constraint: freshservice_domain like '%.freshservice.com' OR freshservice_domain like '%.freshworks.com'
  - constraint: status in ('active','suspended','revoked')
- `people_and_groups.json` — Unified storage for requesters, agents, and their groups (agent groups and requester groups) plus membership edges. Supports create/update/get/list/filter and group membership tools. (30 rows; fields: ['id', 'account_id', 'entity_type', 'freshservice_id', 'group_kind', 'group_visibility', 'parent_group_id', 'member_person_id', 'name', 'email', 'mobile', 'title', 'active', 'custom_fields', 'fields_schema_cache', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'deleted']
  - constraint: unique(account_id, entity_type, freshservice_id) where freshservice_id is not null
  - constraint: unique(account_id, entity_type, email) where entity_type in ('requester','agent') and email is not null and status <> 'deleted'
  - constraint: check(entity_type <> 'group' OR group_kind in ('agent_group','requester_group'))
  - constraint: check(entity_type <> 'group_member' OR (parent_group_id is not null and member_person_id is not null))
- `tickets.json` — Tickets and ticket-related sub-objects (conversations, notes/replies, requested items) needed to implement ticket CRUD, listing/filtering, and conversation/note/reply tools. (34 rows; fields: ['id', 'account_id', 'record_type', 'freshservice_id', 'ticket_id', 'workspace_id', 'requester_id', 'agent_id', 'group_id', 'subject', 'description', 'priority', 'impact', 'urgency', 'category', 'sub_category', 'item_category', 'tags', 'custom_fields', 'conversation_body', 'conversation_type', 'private', 'from_email', 'to_emails', 'cc_emails', 'requested_item_payload', 'ticket_fields_schema_cache', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'pending', 'resolved', 'closed', 'deleted', 'active']
  - constraint: unique(account_id, record_type, freshservice_id) where freshservice_id is not null
  - constraint: check(record_type <> 'ticket' OR (subject is not null))
  - constraint: check(record_type <> 'conversation' OR ticket_id is not null)
  - constraint: check(record_type <> 'note' OR ticket_id is not null)
- `catalog_and_kb.json` — Service catalog items/products and knowledge base objects (solution categories, folders, articles) plus canned responses and folders. Also stores workspaces listing for the account. (34 rows; fields: ['id', 'account_id', 'entity_type', 'freshservice_id', 'parent_id', 'workspace_id', 'name', 'description', 'body', 'tags', 'visibility', 'draft', 'published_at', 'raw_payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted', 'draft', 'published']
  - constraint: unique(account_id, entity_type, freshservice_id)
  - constraint: check(entity_type <> 'solution_folder' OR parent_id is not null)
  - constraint: check(entity_type <> 'solution_article' OR parent_id is not null)
  - constraint: check(entity_type <> 'canned_response' OR parent_id is not null)
- `integration_events.json` — Immutable audit log of tool invocations and resulting mutations for debugging, traceability, and idempotency. Every tool call should write one event with optional links to affected entities. (32 rows; fields: ['id', 'account_id', 'tool_name', 'request_params', 'http_method', 'endpoint', 'status', 'error_message', 'affected_collection', 'affected_id', 'vendor_freshservice_id', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'succeeded', 'failed']
  - constraint: check(duration_ms is null OR duration_ms >= 0)
  - constraint: check((affected_id is null) OR (affected_collection is not null))
  - constraint: fk(account_id) references fs_accounts.id

## Business rules enforced by the tools

- Every tool invocation must be associated with exactly one fs_accounts row with status='active'; otherwise the tool fails and an integration_events row is written with status='failed'.
- get_tickets, filter_tickets, get_ticket_by_id read from tickets where record_type='ticket' and account_id matches; list_all_ticket_conversation reads from tickets where record_type in ('conversation','note') and ticket_id points to the parent ticket.
- create_ticket inserts one tickets row with record_type='ticket' and status in ('open','pending'); update_ticket updates only rows with record_type='ticket' and status<>'deleted'. delete_ticket sets status='deleted' (soft delete) and must not physically remove rows.
- send_ticket_reply and create_ticket_note insert a child row in tickets with record_type='conversation' (reply) or record_type='note' and ticket_id referencing an existing non-deleted ticket; update_ticket_conversation updates only record_type='conversation' rows.
- get_requested_items returns tickets rows where record_type='requested_item' and ticket_id references the service-request ticket; create_service_request must create a ticket row and one or more requested_item child rows.
- Requester/agent tools operate on people_and_groups rows with entity_type='requester' or 'agent'. create_requester/create_agent insert rows with status='active'; update_requester/update_agent cannot modify rows with status='deleted'.
- Group tools operate on people_and_groups rows with entity_type='group'. add_requester_to_group creates a group_member row only if the target group is a requester_group with group_visibility='manual' and the member is a requester; duplicates are prevented by unique(account_id, parent_group_id, member_person_id) enforced at application level.
- Catalog and KB tools operate on catalog_and_kb with entity_type mapping: list_all_workspaces/workspace get -> 'workspace'; get_all_products/create/update -> 'product'; list_service_items -> 'service_item'; solution category/folder/article tools -> 'solution_category'/'solution_folder'/'solution_article'; canned response tools -> 'canned_response'/'canned_response_folder'.
- publish_solution_article transitions catalog_and_kb.status from 'draft' to 'published' for entity_type='solution_article' and sets published_at; publishing is forbidden if status is 'deleted'.
- All list/get/filter tools must support pagination/filters by translating to where clauses on (account_id, entity_type/record_type, freshservice_id, name/email, workspace_id, status) and may fall back to raw_payload/custom_fields JSON querying.
- For all collections, (account_id, entity_type/record_type, freshservice_id) uniqueness must be preserved to prevent duplicate vendor objects when syncing or after repeated tool calls.
- integration_events must be appended for every tool invocation; status must transition queued->(succeeded|failed) exactly once, and duration_ms must be non-negative.