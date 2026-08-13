# Clockify Time Tracking Integration Server — local MCP environment

This backend powers an integration server that proxies Clockify time-tracking operations for an authenticated user: listing/creating workspace entities (clients, projects, tasks, tags) and managing time entries including a running timer. It also persists generated reports and integration audit logs so tools like detailed_report/summary_report and test_clockify_connection can be served consistently and rate-limited per workspace/user connection.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@fahadBSTech/clockify-mcp

## Datastore

- `clockify_connections.json` — Represents an authenticated integration connection to Clockify for a single end-user (the 'authenticated user' for tools). Stores the Clockify API token reference, mapped Clockify user id, default workspace selection, and connection health. (12 rows; fields: ['id', 'provider', 'external_user_id', 'external_user_email', 'api_key_ciphertext', 'default_workspace_id', 'last_success_at', 'last_error_at', 'last_error_message', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(provider, external_user_id)
  - constraint: status in ('active','revoked','error')
  - constraint: api_key_ciphertext is encrypted-at-rest and never selectable via public tool responses
- `workspaces.json` — Clockify workspaces visible to an authenticated connection. Used by get_workspaces/get_workspace and as a parent for clients/projects/tags/users/time entries. (12 rows; fields: ['id', 'connection_id', 'external_workspace_id', 'name', 'membership_role', 'status', 'synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(connection_id, external_workspace_id)
  - constraint: name <> ''
  - constraint: status in ('active','archived')
- `workspace_entities.json` — Unified store for per-workspace objects: users, clients, projects, tasks, and tags. This reflects the Clockify domain while keeping collection count low; entity_type differentiates schemas. Supports get_users/get_clients/get_projects/get_tasks/get_tags and create_client/create_project/create_task/create_tag. (33 rows; fields: ['id', 'workspace_id', 'entity_type', 'external_id', 'name', 'email', 'project_id', 'client_id', 'billable', 'archived', 'color', 'status', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(workspace_id, entity_type, external_id)
  - constraint: entity_type in ('user','client','project','task','tag')
  - constraint: if entity_type='task' then project_id is not null
  - constraint: if entity_type='project' and client_id is not null then referenced client_id must point to entity_type='client' in same workspace
- `time_entries.json` — Time tracking records including running timers. Serves get_time_entries/create_time_entry/start_timer/stop_timer and is also the basis for report generation. (18 rows; fields: ['id', 'workspace_id', 'user_entity_id', 'external_time_entry_id', 'project_entity_id', 'task_entity_id', 'client_entity_id', 'description', 'billable', 'start_at', 'end_at', 'duration_seconds', 'tag_entity_ids', 'status', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'stopped', 'deleted']
  - constraint: unique(workspace_id, external_time_entry_id) where external_time_entry_id is not null
  - constraint: duration_seconds is null when status='running'
  - constraint: end_at is null when status='running'
  - constraint: end_at >= start_at when end_at is not null
- `reports.json` — Persisted report requests and materialized results to serve detailed_report and summary_report, and to support auditing/report caching. (20 rows; fields: ['id', 'workspace_id', 'requested_by_user_entity_id', 'report_type', 'time_from', 'time_to', 'filters', 'status', 'result', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed']
  - constraint: report_type in ('detailed','summary')
  - constraint: if time_from is not null and time_to is not null then time_to >= time_from
  - constraint: requested_by_user_entity_id must reference entity_type='user' in same workspace
  - constraint: result is not null only when status='completed'

## Business rules enforced by the tools

- All tools operate in the context of exactly one active clockify_connections row; if none exists or status!='active', test_clockify_connection may be called but other tools must fail with an auth/connection error.
- get_workspaces returns all workspaces where connection_id matches the active connection; get_workspace returns the default workspace if set, otherwise the first active workspace by name (deterministic).
- get_user returns the Clockify user mapped by clockify_connections.external_user_id; if no corresponding workspace_entities(user) exists for the default workspace, the system must upsert it before returning.
- get_users/get_clients/get_projects/get_tags return workspace_entities filtered by entity_type and workspace_id (default workspace when none is explicitly selected by server configuration).
- create_client/create_project/create_task/create_tag must create a corresponding workspace_entities row with status='active' and must also create it in Clockify; on provider failure, the local row must not be committed (or must be marked status='deleted' with raw error details).
- create_task requires a valid project (workspace_entities.entity_type='project'); the stored task.project_id must reference that project row.
- get_tasks returns workspace_entities where entity_type='task' and project_id matches the selected project.
- get_time_entries returns time_entries for the authenticated user within the selected workspace; optionally filtered by time window when the server is configured to do so (otherwise returns a reasonable bounded default window to avoid unbounded scans).
- start_timer must ensure there is no existing time_entries row with status='running' for the same (workspace_id, user_entity_id); if one exists, it must either stop it first (creating an end_at and duration_seconds) or reject the request (implementation choice), but must be consistent.
- stop_timer finds the single running time_entries row for (workspace_id, user_entity_id) and transitions it to status='stopped' with end_at=now and duration_seconds computed; if none exists, it must be a no-op or return a 'no running timer' error (implementation choice), but must not create a new entry.
- A time entry may reference task_entity_id only if it also references project_entity_id; and the task must belong to that project (enforced by validating workspace_entities.task.project_id == project_entity_id).
- Tags on time entries must reference workspace_entities rows with entity_type='tag' in the same workspace; invalid tag ids are rejected.
- detailed_report/summary_report must create a reports row (status='queued'), transition through running, then store result and set status='completed' or set status='failed' with error_message; results may be cached by reusing a completed report with identical (workspace_id, report_type, time_from, time_to, filters) within a configured TTL.
- Workspace and entity external ids must be unique per workspace/type as declared; sync/upsert operations must match on (workspace_id, entity_type, external_id) rather than name.
- Deleting/archiving entities must not break referential integrity: a project/client/task/tag referenced by existing time_entries cannot be hard-deleted; instead mark workspace_entities.status='deleted' (soft delete) and keep the row.
- Quota/rate limiting (if enabled) is enforced per connection_id: maximum report generations per hour and maximum Clockify API calls per minute; violations must be logged and the triggering tool must return a limit error.