# Clockify Time Tracking Integration — local MCP environment

This backend stores Clockify workspace data (users, projects, and time entries) plus the service-side notion of an authenticated integration identity used to call Clockify on behalf of a workspace/user. Main workflows: list workspace entities (projects/users), create and query time entries (optionally by date range and/or user), and generate summary reports aggregated by user/project over a date range.

Repository: https://github.com/inakianduaga/clockify-mcp
Homepage: https://smithery.ai/server/@inakianduaga/clockify-mcp

## Datastore

- `workspaces.json` — Clockify workspaces connected to this integration. Holds vendor identifiers and basic metadata used to scope users/projects/time entries. (12 rows; fields: ['id', 'clockify_workspace_id', 'name', 'status', 'default_timezone', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(clockify_workspace_id)
  - constraint: name <> ''
- `integration_identities.json` — Represents the authenticated identity used by the integration (API key / token reference) and its default workspace/user scope. Used to resolve 'authenticated user' tools and enforce per-identity quotas. (12 rows; fields: ['id', 'workspace_id', 'clockify_api_key_hash', 'default_clockify_user_id', 'display_name', 'status', 'requests_per_minute_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(clockify_api_key_hash)
  - constraint: requests_per_minute_limit between 1 and 600
- `users.json` — Users in a workspace (mirrored from Clockify). Supports listing users and matching by name for time-entry queries. (32 rows; fields: ['id', 'workspace_id', 'clockify_user_id', 'email', 'name', 'name_normalized', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, clockify_user_id)
  - constraint: name <> ''
  - constraint: name_normalized = lower(name)
- `projects.json` — Projects in a workspace (mirrored from Clockify). Used by listProjects and to associate time entries to a project. (31 rows; fields: ['id', 'workspace_id', 'clockify_project_id', 'name', 'client_name', 'billable', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, clockify_project_id)
  - constraint: name <> ''
- `time_entries.json` — Time entries created/queried via Clockify. Supports listing by authenticated user or specified user, filtering by ISO8601 date range, and reporting summary by user/project. (33 rows; fields: ['id', 'workspace_id', 'clockify_time_entry_id', 'user_id', 'project_id', 'description', 'start_time', 'end_time', 'duration_seconds', 'billable', 'status', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'stopped', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(user_id) references users(id) on delete restrict
  - constraint: fk(project_id) references projects(id) on delete set null
  - constraint: unique(workspace_id, clockify_time_entry_id) where clockify_time_entry_id is not null

## Business rules enforced by the tools

- All tools execute within the context of exactly one integration_identity; its workspace_id scopes listProjects, listUsers, and all time entry operations.
- listProjects returns projects where workspace_id = integration_identity.workspace_id and status in ('active','archived') (archived inclusion matches typical Clockify listings; callers may filter client-side).
- listUsers returns users where workspace_id = integration_identity.workspace_id and status in ('active','inactive').
- getTimeEntries returns time_entries for user_id resolved from integration_identity.default_clockify_user_id mapped to users.clockify_user_id within the same workspace; if no mapping exists, the service must first sync/resolve the authenticated user and persist default_clockify_user_id and/or a users row.
- getUserTimeEntries requires the specified user to exist in users for the workspace; the service may upsert the user on-demand when fetched from Clockify, but must not create time entries for unknown users.
- getUserTimeEntriesByName performs case-insensitive partial matching against users.name_normalized; if multiple users match, the service must either return a deterministic union ordered by name then id, or require disambiguation (implementation must be consistent and documented).
- Date range filtering: when start and/or end are provided, they are parsed as ISO8601 datetimes; results include entries that overlap the range (start_time < end AND (end_time is null OR end_time > start)) to handle running entries; if only start provided, treat end as 'now'; if only end provided, treat start as '-infinity'.
- addTimeEntry inserts a new time_entries row with source='integration_created'; it must reference an existing project_id in the same workspace (or store null if the upstream allows no project). It must also reference an existing user_id (typically the authenticated user).
- When addTimeEntry creates a stopped entry, it must set end_time and duration_seconds; when it creates a running entry, it must set end_time=null, duration_seconds=null, status='running'.
- Only one running time entry per user per workspace is allowed: enforce via a partial uniqueness constraint unique(workspace_id, user_id) where status='running'.
- getSummaryReport aggregates time_entries within the requested date range and status != 'deleted', grouping by user_id and project_id; it returns total duration_seconds and derived hours = duration_seconds/3600. If userIds/projectIds are provided, they filter against users.clockify_user_id/projects.clockify_project_id within the workspace.
- FK integrity: users.workspace_id, projects.workspace_id, time_entries.workspace_id must all match for referenced rows (enforce via application check or composite foreign keys in SQL).
- Quota/rate limiting: requests against an integration_identity must not exceed requests_per_minute_limit; violating requests must be rejected before mutating operations like addTimeEntry.