# Attio CRM Integration Server — local MCP environment

This backend mirrors an Attio workspace into a local, query-optimized store to power search, advanced filtering, list membership, notes, and task workflows exposed by the Attio CRM Integration Server. Core workflows: create/update/delete company/person (and generic records), run multiple search variants, manage lists and list entries (pipeline/segment membership), attach notes to records, and create/link/manage tasks against records.

Repository: https://github.com/kesslerio/attio-mcp-server
Homepage: https://smithery.ai/server/@kesslerio/attio-mcp-server

## Datastore

- `workspaces.json` — Attio workspace/account boundary for all CRM data. Used to scope uniqueness, permissions, and to store workspace-level attribute/field metadata discovered from Attio. (12 rows; fields: ['id', 'attio_workspace_id', 'name', 'status', 'attribute_catalog', 'last_schema_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleting']
  - constraint: unique(attio_workspace_id)
  - constraint: attribute_catalog must be valid JSON object
  - constraint: updated_at >= created_at
- `records.json` — Generic record store for Attio objects. Companies and People are modeled as record_type values to support both specialized and generic record tools (create-record/get-record/update-record/delete-record/list-records) as well as company/person specific tools via filtered views. (33 rows; fields: ['id', 'workspace_id', 'record_type', 'attio_object', 'attio_record_id', 'status', 'display_name', 'domain', 'email', 'phone', 'social', 'contact', 'business', 'attributes', 'raw_json', 'last_interaction_at', 'last_activity_at', 'attio_created_at', 'attio_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, attio_object, attio_record_id)
  - constraint: record_type in ('company','person','custom')
  - constraint: if record_type='company' then email is nullable and domain may be non-null; if record_type='person' then domain is nullable and email/phone may be non-null
- `lists.json` — CRM lists/pipelines/segments and their entry configuration. Supports get-lists, get-list-details and provides parent for list entry operations. (34 rows; fields: ['id', 'workspace_id', 'attio_list_id', 'name', 'list_type', 'applies_to', 'status', 'field_config', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, attio_list_id)
  - constraint: unique(workspace_id, name)
  - constraint: field_config must be valid JSON object
- `list_entries.json` — Memberships/entries that connect records to lists with entry-level attributes (e.g., pipeline stage, owner, entry fields). Powers get-list-entries, filter-list-entries, advanced-filter-list-entries, add/remove record to list, update-list-entry, get-record-list-memberships, get-company-lists, and list-entry filtering by parent properties/ID. (33 rows; fields: ['id', 'workspace_id', 'list_id', 'record_id', 'attio_entry_id', 'status', 'entry_attributes', 'added_at', 'removed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(list_id) references lists(id) on delete cascade
  - constraint: fk(record_id) references records(id) on delete cascade
  - constraint: unique(list_id, record_id) where status='active'
- `notes_tasks.json` — Unified activity table for record notes and tasks plus task-record linking. Supports get-company-notes/get-person-notes, create-company-note/create-person-note, list-tasks/create-task/update-task/delete-task, and link-record-to-task. Implemented as single table with activity_type and optional task fields to keep collection count bounded. (35 rows; fields: ['id', 'workspace_id', 'activity_type', 'attio_activity_id', 'status', 'author_record_id', 'title', 'body', 'due_at', 'completed_at', 'linked_record_ids', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, attio_activity_id) where attio_activity_id is not null
  - constraint: linked_record_ids length >= 0 and must contain only existing records.id in same workspace (enforced in application/trigger)
  - constraint: if activity_type='note' then due_at is null and completed_at is null

## Business rules enforced by the tools

- All tool operations are scoped to exactly one workspace; workspace_id is derived from the server's configured Attio connection and never accepted directly from clients.
- search-companies/search-people/smart-search-companies perform full-text matching over records.display_name plus selected fields in records.attributes/raw_json; only records.status='active' are returned unless explicitly requesting deleted/archived (not exposed by tools).
- search-companies-by-domain matches records.record_type='company' and records.domain equals normalized input host; normalization strips scheme, path, and 'www.', and lowercases.
- search-people-by-email matches records.record_type='person' and records.email equals normalized lowercase email.
- search-people-by-phone matches records.record_type='person' and records.phone equals normalized E.164 phone when possible; if input cannot be normalized, falls back to digits-only comparison.
- advanced-search-companies/advanced-search-people/advanced-filter-list-entries evaluate boolean expressions over records.attributes and/or list_entries.entry_attributes; invalid attribute keys yield a 400-like error rather than silently ignoring conditions.
- create-company/create-person/create-record insert into records with status='active'; update-company/update-person/update-record mutate records.attributes and update denormalized columns (display_name/domain/email/phone/contact/social/business) consistently.
- update-company-attribute updates exactly one key in records.attributes using an atomic JSON set operation; it must not drop other attributes.
- delete-company/delete-record marks records.status='deleted' (soft delete) and does not physically remove by default; list_entries for that record are set to status='removed' and removed_at is set.
- get-company-fields/get-company-basic-info/get-company-contact-info/get-company-business-info/get-company-social-info are projections over records plus derived fields; get-company-json returns records.raw_json.
- discover-company-attributes returns workspaces.attribute_catalog filtered to company-relevant attributes; get-company-custom-fields returns the subset of attributes flagged custom within attribute_catalog.
- create-company-note/create-person-note create a notes_tasks row with activity_type='note', status='active', and linked_record_ids containing the target record; get-company-notes/get-person-notes filter notes_tasks by activity_type='note' and linked_record_ids containment.
- list-tasks returns notes_tasks rows where activity_type='task' and status != 'deleted'; create-task inserts activity_type='task', status='active'; update-task may change title/body/due_at/status; delete-task sets status='deleted'.
- link-record-to-task appends a record_id to notes_tasks.linked_record_ids for a task; it is idempotent (no duplicates).
- get-lists returns lists where status='active'; get-list-details returns lists.field_config and other metadata.
- get-list-entries returns list_entries where list_id matches and status='active' joined to records for parent properties when needed.
- filter-list-entries and filter-list-entries-by-parent filter on list_entries.entry_attributes or joined records.attributes respectively; filter-list-entries-by-parent-id filters on list_entries.record_id.
- add-record-to-list creates or reactivates a list_entries row (status='active', removed_at null, added_at set). remove-record-from-list sets status='removed' and removed_at.
- update-list-entry mutates list_entries.entry_attributes (e.g., stage changes) and must validate stage IDs against lists.field_config when list_type='pipeline'.
- get-record-list-memberships returns all lists joined through list_entries for the given record_id with list_entries.status='active'.
- batch-create-companies/batch-update-companies/batch-delete-companies and batch-create-records/batch-update-records execute per-item operations within a single request; partial failures return per-item error details and do not roll back successful items unless the server is configured for all-or-nothing.
- batch-search-companies performs multiple independent searches and returns ordered results per search request; each search is subject to server-side maximum result limits.
- batch-get-company-details/get-company-details fetch multiple records by id/attio_record_id and return the requested projections; missing IDs return null/404 per item rather than failing the entire batch.
- FK integrity is enforced such that lists and entries cannot cross workspaces; any attempt to link a record to a list or task in a different workspace is rejected.