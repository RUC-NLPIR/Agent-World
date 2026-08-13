# Clay MCP — local MCP environment

This backend stores a user's Clay CRM data: contacts (with rich identifiers like emails/phones/socials), groups/lists and their membership, notes, interaction history, and calendar events. The main workflows are: searching/aggregating contacts and interactions, creating contacts and notes, listing/creating/updating groups (including membership changes), and fetching notes/events by date range.

Repository: https://github.com/clay-inc/clay-mcp
Homepage: https://smithery.ai/server/@clay-inc/clay-mcp

## Datastore

- `contacts.json` — Core contact records in Clay, including identity, enrichment fields, and key timestamps used for sorting/filtering in search and interaction tools. (18 rows; fields: ['id', 'workspace_id', 'status', 'first_name', 'last_name', 'full_name', 'title', 'company', 'company_domain', 'location', 'emails', 'phones', 'social_links', 'source', 'created_at', 'updated_at', 'last_interaction_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: not null: id, workspace_id, status, created_at, updated_at
  - constraint: emails is array (default []), phones is array (default []), social_links is array (default [])
  - constraint: unique(workspace_id, lower(full_name), lower(company)) WHERE status != 'deleted' (best-effort de-dupe)
  - constraint: each emails[].value must be a valid email format
- `groups.json` — Groups/lists used to organize contacts. Supports retrieval, creation with duplicate-name checks, and membership modifications. (18 rows; fields: ['id', 'workspace_id', 'status', 'name', 'description', 'member_count_cached', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: not null: id, workspace_id, status, name, member_count_cached, created_at, updated_at
  - constraint: member_count_cached >= 0
  - constraint: unique(workspace_id, lower(name)) WHERE status != 'deleted' (used by createGroup duplicate-name check unless explicitly overridden)
  - constraint: updated_at >= created_at
- `group_memberships.json` — Join table mapping contacts to groups/lists. Used by updateGroup for bulk add/remove operations and by getGroups for accurate membership. (18 rows; fields: ['id', 'workspace_id', 'group_id', 'contact_id', 'status', 'added_at', 'removed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: not null: id, workspace_id, group_id, contact_id, status, added_at, created_at, updated_at
  - constraint: unique(group_id, contact_id) (one membership row per pair; status toggles between active/removed)
  - constraint: FK: group_id must exist in groups and have status != 'deleted'
  - constraint: FK: contact_id must exist in contacts and have status != 'deleted'
- `notes.json` — User-authored notes attached to contacts. Retrieved strictly by created_at date range and created via createNote. (18 rows; fields: ['id', 'workspace_id', 'contact_id', 'status', 'content', 'created_by', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: not null: id, workspace_id, contact_id, status, content, created_at, updated_at
  - constraint: content length between 1 and 20000 characters
  - constraint: FK: contact_id must exist in contacts and have status != 'deleted'
  - constraint: workspace_id must equal contacts.workspace_id
- `activities.json` — Timeline data used by searchInteractions (emails, meetings, messages, calls) and by getEvents (calendar events) within a date range. (20 rows; fields: ['id', 'workspace_id', 'status', 'activity_type', 'occurred_at', 'start_at', 'end_at', 'title', 'body_preview', 'location', 'external_source', 'external_id', 'participants', 'primary_contact_id', 'relevance_score', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'cancelled', 'deleted']
  - constraint: not null: id, workspace_id, status, activity_type, occurred_at, participants, created_at, updated_at
  - constraint: relevance_score between 0 and 1 when not null
  - constraint: if activity_type='meeting' then start_at is not null and end_at is not null and end_at >= start_at
  - constraint: if external_source is not null then external_id is not null

## Business rules enforced by the tools

- All tools operate within a single authenticated workspace scope; every read/write must filter by workspace_id and reject cross-workspace foreign keys.
- searchContacts returns only contacts with status in ('active','archived') and must never return status='deleted' records.
- aggregateContacts returns only numeric aggregates (counts/percentages) computed from contacts (and optionally group_memberships) and must not return any contact identifiers or PII fields.
- getContact returns a single contact by contacts.id and includes emails/phones/social_links arrays; request must 404 if the contact is deleted or not in the caller workspace.
- createContact inserts into contacts with status='active', sets created_at/updated_at, and must enforce workspace-level dedupe best-effort (reject or warn on same full_name+company unless caller overrides via internal flag).
- createNote inserts into notes with status='active' and a valid contact_id; content must be non-empty and within length limit; contact must not be deleted.
- getNotes may only filter by notes.created_at date range (inclusive start, exclusive end) and workspace_id; it must not full-text search notes.content and must not filter by contact attributes beyond an explicit contact_id if provided by internal implementation.
- getGroups returns groups with status in ('active','archived') plus their member_count_cached; it must not include deleted groups.
- createGroup must enforce unique(workspace_id, lower(name)) for non-deleted groups unless an explicit ignore-duplicate-check flag is set; on conflict without override, it returns the existing group.
- updateGroup may change groups.name and/or membership in group_memberships; membership changes must be applied in bulk per request (single transaction) and must be idempotent (adding an existing active membership is a no-op; removing a missing membership is a no-op).
- When group_memberships status changes, groups.member_count_cached must be updated to reflect the number of active memberships.
- searchInteractions queries activities within workspace_id and returns matching activity records, and when required by the query, may join contacts via primary_contact_id or participants[].contact_id to return full contact records; deleted activities and deleted contacts must be excluded.
- getEvents returns only activities where activity_type='meeting' (and optionally other calendar-like types) and filters by start_at/end_at overlapping the requested date range; cancelled events may be included only if explicitly requested by internal policy, otherwise excluded.